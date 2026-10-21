"""End-to-end HTTP/HTTPS + OAuth flows for the MCP transport.

These tests use only loopback sockets and in-process apps: no external network
and no real identity provider.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from code_diver.transport.http_server import create_remote_app
from code_diver.transport.mcp_http import SessionLimits
from code_diver.transport.oauth import (
    READ_SCOPE,
    WRITE_SCOPE,
    OAuthProvider,
    OAuthSettings,
    OAuthStore,
    code_challenge_for,
    generate_code_verifier,
)
from code_diver.transport.tls import TLSSettings

ACCEPT = {"accept": "application/json, text/event-stream"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "e2e", "version": "1.0"},
    },
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _LiveServer:
    def __init__(self, app, port: int, **kwargs) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", **kwargs)
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("uvicorn did not start")

    def __exit__(self, *exc_info) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _provider() -> OAuthProvider:
    settings = OAuthSettings(
        enabled=True,
        issuer="http://127.0.0.1:18080",
        resource="http://127.0.0.1:18080/mcp",
        jwt_secret="e" * 48,
        consent_secret="operator-code",
        db_path=":memory:",
    )
    return OAuthProvider(settings, store=OAuthStore(":memory:"))


# ---------------------------------------------------------------------------
# OAuth 2.1 flow (register -> authorize/PKCE -> token -> /mcp)
# ---------------------------------------------------------------------------


def test_oauth_registration_authorization_token_and_mcp() -> None:
    provider = _provider()
    app = create_remote_app("code-diver.yml", oauth=provider)
    client = TestClient(app)

    metadata = client.get("/.well-known/oauth-protected-resource").json()
    assert metadata["resource"] == "http://127.0.0.1:18080/mcp"
    as_metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert as_metadata["issuer"] == "http://127.0.0.1:18080"

    registration = client.post(
        "/register",
        json={
            "client_name": "Claude Desktop",
            "redirect_uris": ["http://127.0.0.1:4444/callback"],
            "scope": f"{READ_SCOPE} {WRITE_SCOPE}",
        },
    )
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]

    verifier = generate_code_verifier()
    authorize_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "http://127.0.0.1:4444/callback",
        "scope": READ_SCOPE,
        "state": "roundtrip",
        "code_challenge": code_challenge_for(verifier),
        "code_challenge_method": "S256",
    }
    consent = client.get("/authorize", params=authorize_params)
    assert consent.status_code == 200
    assert "Operator access code" in consent.text

    approved = client.post(
        "/authorize", data={**authorize_params, "consent": "operator-code"}, follow_redirects=False
    )
    assert approved.status_code == 302
    callback = approved.headers["location"]
    query = parse_qs(urlsplit(callback).query)
    assert query["state"] == ["roundtrip"]
    code = query["code"][0]

    token_response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://127.0.0.1:4444/callback",
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token_response.status_code == 200
    tokens = token_response.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["scope"] == READ_SCOPE

    headers = {**ACCEPT, "authorization": f"Bearer {tokens['access_token']}"}
    initialized = client.post("/mcp", json=INIT, headers=headers)
    assert initialized.status_code == 200
    session_id = initialized.headers["mcp-session-id"]

    tool_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "code_diver_grep", "arguments": {"pattern": "Streamable", "limit": 3}},
        },
        headers={**headers, "mcp-session-id": session_id},
    )
    result = tool_call.json()["result"]
    assert result["isError"] is False
    assert '"path"' in result["content"][0]["text"]

    # Refresh keeps the same scope and rotates the refresh token.
    refreshed = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
        },
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["scope"] == READ_SCOPE
    new_access = refreshed.json()["access_token"]
    assert new_access != tokens["access_token"]

    # Revocation immediately invalidates the new access token.
    assert client.post("/revoke", data={"token": new_access, "client_id": client_id}).status_code == 200
    rejected = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        headers={**ACCEPT, "authorization": f"Bearer {new_access}", "mcp-session-id": session_id},
    )
    assert rejected.status_code == 401
    assert 'error="invalid_token"' in rejected.headers["WWW-Authenticate"]


def test_unauthenticated_mcp_gets_resource_metadata_challenge() -> None:
    app = create_remote_app("code-diver.yml", oauth=_provider())
    client = TestClient(app)
    response = client.post("/mcp", json=INIT, headers=ACCEPT)
    assert response.status_code == 401
    challenge = response.headers["WWW-Authenticate"]
    assert challenge.startswith("Bearer ")
    assert "resource_metadata=" in challenge
    assert "/.well-known/oauth-protected-resource" in challenge


# ---------------------------------------------------------------------------
# Live HTTP with the official MCP SDK
# ---------------------------------------------------------------------------


def test_live_http_official_sdk_client_two_sessions_share_runtime() -> None:
    port = _free_port()
    app = create_remote_app("code-diver.yml", oauth=False)
    with _LiveServer(app, port):
        from mcp import Client

        async def run(mode: str) -> None:
            async with Client(f"http://127.0.0.1:{port}/mcp", mode=mode) as mcp_client:
                tools = await mcp_client.list_tools()
                assert any(tool.name == "code_diver_grep" for tool in tools.tools)
                result = await mcp_client.call_tool(
                    "code_diver_grep",
                    {"pattern": "create_remote_app", "path": "src/code_diver/transport", "limit": 2},
                )
                assert result.is_error is False
                assert "create_remote_app" in str(result.content[0].text)

        asyncio.run(run("auto"))
        asyncio.run(run("legacy"))

        stats = httpx.get(f"http://127.0.0.1:{port}/api/v1/runtime/stats", timeout=10).json()
        assert stats["runtime_loads"] == 1
        assert stats["mcp_sessions"]["created_total"] == 2
        assert stats["mcp_sessions"]["deleted_total"] == 2


def test_live_http_sse_get_stream() -> None:
    port = _free_port()
    app = create_remote_app(
        "code-diver.yml", oauth=False, session_limits=SessionLimits(ping_interval=1)
    )
    with _LiveServer(app, port), httpx.Client(timeout=10) as client:
        initialized = client.post(f"http://127.0.0.1:{port}/mcp", json=INIT, headers=ACCEPT)
        session_id = initialized.headers["mcp-session-id"]
        with client.stream(
            "GET",
            f"http://127.0.0.1:{port}/mcp",
            headers={"accept": "text/event-stream", "mcp-session-id": session_id},
        ) as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            first_line = next(stream.iter_lines())
            assert first_line.startswith((":", "event:"))


# ---------------------------------------------------------------------------
# Live HTTPS
# ---------------------------------------------------------------------------


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem_key(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _pem_cert(cert) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _build_certs(directory):
    now = datetime.now(UTC)

    def build(subject, key, issuer_cert=None, issuer_key=None):
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
        builder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(issuer_cert.subject if issuer_cert else name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.BasicConstraints(ca=issuer_cert is None, path_length=None), critical=True)
        )
        if issuer_cert is not None:
            builder = builder.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
                critical=False,
            )
        return builder.sign(issuer_key or key, hashes.SHA256())

    ca_key = _key()
    ca = build("code-diver e2e CA", ca_key)
    server_key = _key()
    server = build("code-diver e2e server", server_key, ca, ca_key)
    paths = {
        "ca": directory / "ca.pem",
        "cert": directory / "server.pem",
        "key": directory / "server.key",
    }
    paths["ca"].write_bytes(_pem_cert(ca))
    paths["cert"].write_bytes(_pem_cert(server))
    paths["key"].write_bytes(_pem_key(server_key))
    paths["key"].chmod(0o600)
    return paths


def test_live_https_mcp_initialize_and_tool_call(tmp_path) -> None:
    certs = _build_certs(tmp_path)
    port = _free_port()
    app = create_remote_app("code-diver.yml", oauth=False)
    tls = TLSSettings.from_env({}, cert=certs["cert"], key=certs["key"])
    with _LiveServer(app, port, **tls.uvicorn_kwargs()):
        context = ssl.create_default_context(cafile=str(certs["ca"]))
        with httpx.Client(verify=context, timeout=10) as client:
            initialized = client.post(f"https://127.0.0.1:{port}/mcp", json=INIT, headers=ACCEPT)
            assert initialized.status_code == 200
            session_id = initialized.headers["mcp-session-id"]
            tool = client.post(
                f"https://127.0.0.1:{port}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "code_diver_read",
                        "arguments": {"file": "src/code_diver/transport/tls.py", "lines": 5},
                    },
                },
                headers={**ACCEPT, "mcp-session-id": session_id},
            )
            result = tool.json()["result"]
            assert result["isError"] is False
            assert "TLS configuration" in result["content"][0]["text"]
            # Plain HTTP against the TLS port must not silently work.
            with pytest.raises(httpx.HTTPError):
                httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
