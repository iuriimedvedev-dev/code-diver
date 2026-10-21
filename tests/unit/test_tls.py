"""Tests for TLS settings and a live HTTPS/mTLS smoke test."""

from __future__ import annotations

import ipaddress
import socket
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from code_diver.transport.http_server import create_remote_app
from code_diver.transport.tls import TLSConfigError, TLSSettings


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _write_key(path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _write_cert(path, cert) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _certificate(*, subject: str, key, issuer_cert=None, issuer_key=None, ca: bool = False, client: bool = False):
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(issuer_cert.subject if issuer_cert else _name(subject))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )
    if issuer_cert is not None and issuer_key is not None:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
    if ca:
        builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    if client:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
    return builder.sign(issuer_key or key, hashes.SHA256())


def _client_context(ca_path) -> ssl.SSLContext:
    """Build a verifying client context (httpx's deprecated verify=str path drops client certs)."""
    return ssl.create_default_context(cafile=str(ca_path))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _LiveServer:
    def __init__(self, app, port: int, **ssl_kwargs) -> None:
        self.config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", **ssl_kwargs
        )
        self.server = uvicorn.Server(self.config)
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


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    base = tmp_path_factory.mktemp("tls")
    ca_key = _key()
    ca_cert = _certificate(subject="code-diver test CA", key=ca_key, ca=True)
    server_key = _key()
    server_cert = _certificate(subject="code-diver test server", key=server_key, issuer_cert=ca_cert, issuer_key=ca_key)
    client_key = _key()
    client_cert = _certificate(
        subject="code-diver test client", key=client_key, issuer_cert=ca_cert, issuer_key=ca_key, client=True
    )
    paths = {
        "ca": base / "ca.pem",
        "server_cert": base / "server.pem",
        "server_key": base / "server.key",
        "client_cert": base / "client.pem",
        "client_key": base / "client.key",
    }
    _write_cert(paths["ca"], ca_cert)
    _write_cert(paths["server_cert"], server_cert)
    _write_key(paths["server_key"], server_key)
    _write_cert(paths["client_cert"], client_cert)
    _write_key(paths["client_key"], client_key)
    paths["server_key"].chmod(0o600)
    paths["client_key"].chmod(0o600)
    return paths


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_tls_disabled_by_default() -> None:
    settings = TLSSettings.from_env({})
    assert settings.enabled is False
    assert settings.scheme == "http"
    assert settings.uvicorn_kwargs() == {}


def test_tls_requires_cert_and_key_together(certs) -> None:
    with pytest.raises(TLSConfigError, match="together"):
        TLSSettings.from_env({}, cert=certs["server_cert"])


def test_tls_rejects_missing_files(tmp_path) -> None:
    with pytest.raises(TLSConfigError, match="does not exist"):
        TLSSettings.from_env({}, cert=tmp_path / "missing.pem", key=tmp_path / "missing.key")


def test_tls_requires_ca_for_mutual_auth(certs) -> None:
    with pytest.raises(TLSConfigError, match="CLIENT_CA"):
        TLSSettings.from_env(
            {}, cert=certs["server_cert"], key=certs["server_key"], require_client_cert=True
        )


def test_tls_uvicorn_kwargs(certs) -> None:
    settings = TLSSettings.from_env(
        {}, cert=certs["server_cert"], key=certs["server_key"]
    )
    kwargs = settings.uvicorn_kwargs()
    assert kwargs["ssl_certfile"].endswith("server.pem")
    assert kwargs["ssl_keyfile"].endswith("server.key")
    assert "ssl_cert_reqs" not in kwargs
    assert settings.base_url("0.0.0.0", 8443) == "https://127.0.0.1:8443"

    mutual = TLSSettings.from_env(
        {},
        cert=certs["server_cert"],
        key=certs["server_key"],
        client_ca=certs["ca"],
        require_client_cert=True,
    )
    assert mutual.uvicorn_kwargs()["ssl_cert_reqs"] == ssl.CERT_REQUIRED


# ---------------------------------------------------------------------------
# Live HTTPS
# ---------------------------------------------------------------------------


def test_https_roundtrip(certs) -> None:
    port = _free_port()
    app = create_remote_app("code-diver.yml", oauth=False)
    settings = TLSSettings.from_env({}, cert=certs["server_cert"], key=certs["server_key"])
    with _LiveServer(app, port, **settings.uvicorn_kwargs()):
        with httpx.Client(verify=_client_context(certs["ca"]), timeout=10) as client:
            response = client.get(f"https://127.0.0.1:{port}/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        with pytest.raises((httpx.ConnectError, httpx.RemoteProtocolError)):
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)


def test_mtls_requires_client_certificate(certs) -> None:
    port = _free_port()
    app = create_remote_app("code-diver.yml", oauth=False)
    settings = TLSSettings.from_env(
        {},
        cert=certs["server_cert"],
        key=certs["server_key"],
        client_ca=certs["ca"],
        require_client_cert=True,
    )
    with _LiveServer(app, port, **settings.uvicorn_kwargs()):
        with httpx.Client(
            verify=_client_context(certs["ca"]),
            cert=(str(certs["client_cert"]), str(certs["client_key"])),
            timeout=10,
        ) as client:
            assert client.get(f"https://127.0.0.1:{port}/health").status_code == 200
        with (
            httpx.Client(verify=_client_context(certs["ca"]), timeout=10) as anonymous,
            pytest.raises((httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, ssl.SSLError)),
        ):
            anonymous.get(f"https://127.0.0.1:{port}/health")
