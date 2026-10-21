"""Unit/integration tests for the standard MCP Streamable HTTP transport."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from code_diver.config import ConfigLoader
from code_diver.transport.http_server import create_remote_app
from code_diver.transport.mcp_http import (
    MCP_PROTOCOL_HEADER,
    MCP_SESSION_HEADER,
    SessionLimits,
)
from code_diver.transport.oauth import (
    READ_SCOPE,
    WRITE_SCOPE,
    OAuthProvider,
    OAuthSettings,
    OAuthStore,
)

ACCEPT_BOTH = {"accept": "application/json, text/event-stream"}
ACCEPT_JSON = {"accept": "application/json"}
INIT_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {"roots": {"listChanged": False}},
    "clientInfo": {"name": "pytest", "version": "1.0"},
}


@dataclass
class _FakeItem:
    path: str = "src/example.py"
    start_line: int = 1
    end_line: int = 5
    title: str = "example"
    content: str = "def example() -> None:\n    pass\n"


@dataclass
class _FakeResult:
    item: _FakeItem
    score: float = 0.91


class _FakeStrategy:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, limit: int = 10):
        self.calls += 1
        return [_FakeResult(_FakeItem()) for _ in range(min(limit, 1))]


class _FakeRuntime:
    def __init__(self) -> None:
        self.base_strategy = _FakeStrategy()


class _RuntimeFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, resolved: Path):
        self.calls += 1
        return ConfigLoader().load(resolved), _FakeRuntime()


def _app(**kwargs):
    factory = _RuntimeFactory()
    app = create_remote_app("code-diver.yml", oauth=False, runtime_factory=factory, **kwargs)
    return app, factory


def _initialize(client: TestClient, headers: dict[str, str] | None = None) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS}
    response = client.post("/mcp", json=payload, headers={**ACCEPT_BOTH, **(headers or {})})
    assert response.status_code == 200, response.text
    return response.headers[MCP_SESSION_HEADER]


def _call(client: TestClient, session_id: str, method: str, params: dict | None = None, request_id: int = 2):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post(
        "/mcp",
        json=payload,
        headers={**ACCEPT_BOTH, MCP_SESSION_HEADER: session_id},
    )


# ---------------------------------------------------------------------------
# Transport lifecycle
# ---------------------------------------------------------------------------


def test_initialize_returns_session_and_server_info() -> None:
    app, _ = _app()
    client = TestClient(app)
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS}, headers=ACCEPT_BOTH
    )
    assert response.status_code == 200
    assert response.headers[MCP_SESSION_HEADER]
    result = response.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "code-diver"
    assert "tools" in result["capabilities"]


def test_notification_is_accepted_without_body() -> None:
    app, _ = _app()
    client = TestClient(app)
    session_id = _initialize(client)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**ACCEPT_BOTH, MCP_SESSION_HEADER: session_id},
    )
    assert response.status_code == 202
    assert response.content == b""


def test_missing_and_unknown_session() -> None:
    app, _ = _app()
    client = TestClient(app)
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"}, headers=ACCEPT_BOTH
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
        headers={**ACCEPT_BOTH, MCP_SESSION_HEADER: "does-not-exist"},
    )
    assert response.status_code == 404


def test_delete_terminates_session() -> None:
    app, _ = _app()
    client = TestClient(app)
    session_id = _initialize(client)
    response = client.delete("/mcp", headers={MCP_SESSION_HEADER: session_id})
    assert response.status_code == 204
    assert _call(client, session_id, "tools/list").status_code == 404


def test_invalid_protocol_version_for_established_session() -> None:
    app, _ = _app()
    client = TestClient(app)
    session_id = _initialize(client)
    response = _call_with_headers(
        client, session_id, "tools/list", {MCP_PROTOCOL_HEADER: "1999-01-01"}
    )
    assert response.status_code == 400
    assert "supported" in response.json()["error"]["data"]


def _call_with_headers(client: TestClient, session_id: str, method: str, extra: dict[str, str]):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 5, "method": method},
        headers={**ACCEPT_BOTH, MCP_SESSION_HEADER: session_id, **extra},
    )


def test_accept_header_negotiation() -> None:
    app, _ = _app()
    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers=ACCEPT_JSON,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": INIT_PARAMS},
        headers={"accept": "text/event-stream"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.startswith("event: message")

    rejected = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": INIT_PARAMS},
        headers={"accept": "text/html"},
    )
    assert rejected.status_code == 406


def test_batch_requests_rejected() -> None:
    app, _ = _app()
    client = TestClient(app)
    response = client.post(
        "/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=ACCEPT_BOTH
    )
    assert response.status_code == 400


def test_body_size_limit() -> None:
    app, _ = _app(session_limits=SessionLimits(max_request_bytes=128))
    client = TestClient(app)
    response = client.post(
        "/mcp",
        content=b"{" + b" " * 400 + b"}",
        headers={**ACCEPT_BOTH, "content-type": "application/json"},
    )
    assert response.status_code == 413


def test_get_stream_requires_session() -> None:
    app, _ = _app()
    client = TestClient(app)
    assert client.get("/mcp", headers={"accept": "text/event-stream"}).status_code == 404


def test_max_sessions_enforced() -> None:
    app, _ = _app(session_limits=SessionLimits(max_sessions=1))
    client = TestClient(app)
    _initialize(client)
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS}, headers=ACCEPT_BOTH
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Tools and shared runtime
# ---------------------------------------------------------------------------


def test_tools_list_and_call() -> None:
    app, factory = _app()
    client = TestClient(app)
    session_id = _initialize(client)
    tools = _call(client, session_id, "tools/list").json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"code_diver_search", "code_diver_grep", "code_diver_read", "code_diver_tree"} <= names
    assert "code_diver_index_trigger" in names

    response = _call(
        client,
        session_id,
        "tools/call",
        {"name": "code_diver_search", "arguments": {"query": "example", "limit": 3}},
    )
    result = response.json()["result"]
    assert result["isError"] is False
    assert "src/example.py" in result["content"][0]["text"]
    assert factory.calls == 1

    grep = _call(
        client,
        session_id,
        "tools/call",
        {"name": "code_diver_grep", "arguments": {"pattern": "create_remote_app", "limit": 3}},
    )
    assert grep.json()["result"]["isError"] is False


def test_unknown_tool_and_failed_tool() -> None:
    app, _ = _app()
    client = TestClient(app)
    session_id = _initialize(client)
    response = _call(
        client, session_id, "tools/call", {"name": "nope", "arguments": {}}
    )
    assert response.json()["error"]["code"] == -32601

    response = _call(
        client, session_id, "tools/call", {"name": "code_diver_search", "arguments": {}}
    )
    result = response.json()["result"]
    assert result["isError"] is True
    assert "query is required" in result["content"][0]["text"]


def test_shared_runtime_across_many_sessions() -> None:
    app, factory = _app()
    client = TestClient(app)
    session_ids = [_initialize(client) for _ in range(6)]
    assert len(set(session_ids)) == 6
    for index, session_id in enumerate(session_ids):
        response = _call(
            client,
            session_id,
            "tools/call",
            {"name": "code_diver_search", "arguments": {"query": f"q{index}", "limit": 1}},
            request_id=10 + index,
        )
        assert response.json()["result"]["isError"] is False
    stats = client.get("/api/v1/runtime/stats").json()
    assert factory.calls == 1
    assert stats["runtime_loads"] == 1
    assert stats["mcp_sessions"]["active"] == 6
    assert stats["tools"]["tool_calls_total"] == 6


def test_legacy_json_rpc_alias_still_works() -> None:
    app, _ = _app()
    client = TestClient(app)
    response = client.post(
        "/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response.status_code == 200
    assert len(response.json()["result"]["tools"]) >= 6

    # A pre-spec client POSTs to /mcp without an SSE-capable Accept header.
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 200
    assert len(response.json()["result"]["tools"]) >= 6


def test_server_discover_returns_method_not_found_for_modern_fallback() -> None:
    app, _ = _app()
    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}},
        headers={**ACCEPT_BOTH, MCP_PROTOCOL_HEADER: "2026-07-28"},
    )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# OAuth-scoped behaviour
# ---------------------------------------------------------------------------


def _oauth_app():
    settings = OAuthSettings(
        enabled=True,
        issuer="http://127.0.0.1:18080",
        resource="http://127.0.0.1:18080/mcp",
        jwt_secret="s" * 48,
        consent_secret="consent",
        db_path=":memory:",
    )
    provider = OAuthProvider(settings, store=OAuthStore(":memory:"))
    app = create_remote_app("code-diver.yml", oauth=provider)
    return app, provider


def _token(provider: OAuthProvider, scopes: list[str], subject: str = "subject-a") -> str:
    return provider.mint_access_token(subject=subject, client_id=subject, scopes=scopes)


def test_oauth_required_and_write_scope_hidden() -> None:
    app, provider = _oauth_app()
    client = TestClient(app)
    unauthorized = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers=ACCEPT_BOTH,
    )
    assert unauthorized.status_code == 401
    assert "resource_metadata=" in unauthorized.headers["WWW-Authenticate"]

    token = _token(provider, [READ_SCOPE])
    headers = {**ACCEPT_BOTH, "authorization": f"Bearer {token}"}
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS}, headers=headers
    )
    session_id = response.headers[MCP_SESSION_HEADER]
    tools = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={**headers, MCP_SESSION_HEADER: session_id},
    ).json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "code_diver_index_trigger" not in names
    assert "code_diver_search" in names

    denied = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "code_diver_index_trigger", "arguments": {}},
        },
        headers={**headers, MCP_SESSION_HEADER: session_id},
    )
    assert denied.status_code == 200
    assert denied.json()["error"]["code"] == -32003


def test_session_is_bound_to_bearer_subject() -> None:
    app, provider = _oauth_app()
    client = TestClient(app)
    token_a = _token(provider, [READ_SCOPE], subject="a")
    token_b = _token(provider, [READ_SCOPE], subject="b")
    session_id = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers={**ACCEPT_BOTH, "authorization": f"Bearer {token_a}"},
    ).headers[MCP_SESSION_HEADER]
    stolen = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={
            **ACCEPT_BOTH,
            "authorization": f"Bearer {token_b}",
            MCP_SESSION_HEADER: session_id,
        },
    )
    assert stolen.status_code == 404


def test_write_scope_exposes_write_tools() -> None:
    app, provider = _oauth_app()
    client = TestClient(app)
    token = _token(provider, [READ_SCOPE, WRITE_SCOPE])
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers={**ACCEPT_BOTH, "authorization": f"Bearer {token}"},
    )
    session_id = response.headers[MCP_SESSION_HEADER]
    tools = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={**ACCEPT_BOTH, "authorization": f"Bearer {token}", MCP_SESSION_HEADER: session_id},
    ).json()["result"]["tools"]
    assert "code_diver_index_trigger" in {tool["name"] for tool in tools}


def test_oauth_disabled_legacy_root() -> None:
    app, _ = _app()
    client = TestClient(app)
    assert client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 200


def test_oauth_enabled_disables_root_alias() -> None:
    app, provider = _oauth_app()
    client = TestClient(app)
    token = _token(provider, [READ_SCOPE])
    response = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Write tools: scope + path confinement
# ---------------------------------------------------------------------------


def _write_app(tmp_path, *, index_runner=None):
    config = tmp_path / "code-diver.yml"
    config.write_text(f"root: {tmp_path}\nartifact: {tmp_path / 'index.json'}\n", encoding="utf-8")
    factory = _RuntimeFactory()
    settings = OAuthSettings(
        enabled=True,
        issuer="http://127.0.0.1:18080",
        resource="http://127.0.0.1:18080/mcp",
        jwt_secret="s" * 48,
        consent_secret="consent",
        db_path=":memory:",
    )
    provider = OAuthProvider(settings, store=OAuthStore(":memory:"))
    app = create_remote_app(
        config, oauth=provider, runtime_factory=factory, index_runner=index_runner
    )
    return app, provider


def test_ingest_path_traversal_is_rejected(tmp_path) -> None:
    app, provider = _write_app(tmp_path)
    client = TestClient(app)
    token = _token(provider, [READ_SCOPE, WRITE_SCOPE])
    headers = {**ACCEPT_BOTH, "authorization": f"Bearer {token}"}
    session_id = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS}, headers=headers
    ).headers[MCP_SESSION_HEADER]
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "code_diver_index_ingest",
                "arguments": {"files": [{"path": "../../escape.txt", "content": "nope"}]},
            },
        },
        headers={**headers, MCP_SESSION_HEADER: session_id},
    )
    result = response.json()["result"]
    assert result["isError"] is True
    assert "escapes the ingest directory" in result["content"][0]["text"]
    assert not (tmp_path.parent / "escape.txt").exists()

    ok = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "code_diver_index_ingest",
                "arguments": {"files": [{"path": "sub/demo.py", "content": "x = 1\n"}]},
            },
        },
        headers={**headers, MCP_SESSION_HEADER: session_id},
    )
    payload = json.loads(ok.json()["result"]["content"][0]["text"])
    assert payload["files_received"] == 1
    assert (tmp_path / ".code_diver_remote_ingest" / "sub" / "demo.py").read_text() == "x = 1\n"


def test_index_trigger_validates_path_before_queueing(tmp_path) -> None:
    calls: list[dict] = []

    def runner(request: dict) -> dict:
        calls.append(request)
        return {"status": "completed", "repo_path": request["repo_path"]}

    app, provider = _write_app(tmp_path, index_runner=runner)
    client = TestClient(app)
    token = _token(provider, [READ_SCOPE, WRITE_SCOPE])
    headers = {**ACCEPT_BOTH, "authorization": f"Bearer {token}"}
    session_id = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS}, headers=headers
    ).headers[MCP_SESSION_HEADER]

    rejected = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "code_diver_index_trigger", "arguments": {"repo_path": "/tmp"}},
        },
        headers={**headers, MCP_SESSION_HEADER: session_id},
    )
    result = rejected.json()["result"]
    assert result["isError"] is True
    assert "inside the configured repository root" in result["content"][0]["text"]
    assert calls == []

    accepted = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "code_diver_index_trigger", "arguments": {"repo_path": str(tmp_path)}},
        },
        headers={**headers, MCP_SESSION_HEADER: session_id},
    )
    task = json.loads(accepted.json()["result"]["content"][0]["text"])
    assert task["task_id"].startswith("task_")
    deadline = time.time() + 5
    status = None
    while time.time() < deadline:
        status = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "code_diver_task_status", "arguments": {"task_id": task["task_id"]}},
            },
            headers={**headers, MCP_SESSION_HEADER: session_id},
        ).json()["result"]["content"][0]["text"]
        if json.loads(status)["status"] != "working":
            break
        time.sleep(0.05)
    assert json.loads(status)["status"] == "completed"
    assert calls and calls[0]["repo_path"] == str(tmp_path)


def test_cross_origin_browser_requests_are_rejected() -> None:
    app, _ = _app()
    client = TestClient(app)
    rejected = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers={**ACCEPT_BOTH, "origin": "https://evil.example"},
    )
    # Default configuration is permissive ("*"); restrict explicitly:
    app2 = create_remote_app("code-diver.yml", oauth=False, cors_origins=["https://app.example"])
    client2 = TestClient(app2)
    blocked = client2.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers={**ACCEPT_BOTH, "origin": "https://evil.example"},
    )
    assert blocked.status_code == 403
    allowed = client2.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers={**ACCEPT_BOTH, "origin": "https://app.example"},
    )
    assert allowed.status_code == 200
    assert rejected.status_code == 200  # permissive default for backwards compatibility
