"""Unit and integration tests for Code Diver remote transports (HTTP, SSE, and gRPC)."""

from __future__ import annotations

import asyncio
from concurrent import futures
import json
from pathlib import Path
import threading
from typing import Generator

from fastapi.testclient import TestClient
import grpc
import pytest

from code_diver.transport.grpc_gen import code_diver_pb2, code_diver_pb2_grpc
from code_diver.transport.grpc_server import CodeDiverGrpcServicer
from code_diver.transport.http_server import create_remote_app


@pytest.fixture
def http_client() -> TestClient:
    app = create_remote_app("code-diver.yml")
    return TestClient(app)


def test_http_health(http_client: TestClient) -> None:
    res = http_client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": "0.4.2"}


def test_http_api_info(http_client: TestClient) -> None:
    res = http_client.get("/api/v1/info")
    assert res.status_code == 200
    data = res.json()
    assert "vector_store" in data or "strategy" in data or "runtime" in data or "root" in data or "embedding" in data


def test_http_api_grep(http_client: TestClient) -> None:
    res = http_client.post(
        "/api/v1/grep",
        json={"pattern": "create_remote_app", "path": "src/code_diver/transport"},
    )
    assert res.status_code == 200
    matches = res.json().get("matches", [])
    assert len(matches) > 0
    assert any("create_remote_app" in m["text"] for m in matches)


def test_http_api_tree(http_client: TestClient) -> None:
    res = http_client.post(
        "/api/v1/tree",
        json={"path": "src/code_diver/transport", "depth": 2},
    )
    assert res.status_code == 200
    assert "tree" in res.json()
    assert "grpc_server.py" in res.json()["tree"]


def test_http_api_symbols(http_client: TestClient) -> None:
    res = http_client.post(
        "/api/v1/symbols",
        json={"path": "src/code_diver/transport/grpc_server.py", "limit": 20},
    )
    assert res.status_code == 200
    syms = res.json().get("symbols", [])
    assert len(syms) > 0
    names = [s["name"] for s in syms]
    assert "CodeDiverGrpcServicer" in names


def test_acp_http_lifecycle(http_client: TestClient) -> None:
    # 1. Initialize
    init_res = http_client.post(
        "/acp/v1/rpc",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert init_res.status_code == 200
    init_data = init_res.json()
    assert init_data["result"]["protocolVersion"] == 1
    assert init_data["result"]["agentInfo"]["name"] == "code-diver"

    # 2. Session new
    sess_res = http_client.post(
        "/acp/v1/rpc",
        json={"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "."}},
    )
    assert sess_res.status_code == 200
    sess_id = sess_res.json()["result"]["sessionId"]
    assert sess_id.startswith("sess_")

    # 3. Session prompt
    prompt_res = http_client.post(
        "/acp/v1/rpc",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "sessionId": sess_id,
                "prompt": [{"type": "text", "text": "find CodeDiverGrpcServicer"}],
            },
        },
    )
    assert prompt_res.status_code == 200
    assert prompt_res.json()["result"]["stopReason"] == "end_turn"

    # 4. Session close
    close_res = http_client.post(
        "/acp/v1/rpc",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "session/close",
            "params": {"sessionId": sess_id},
        },
    )
    assert close_res.status_code == 200


@pytest.fixture(scope="module")
def grpc_channel() -> Generator[grpc.Channel, None, None]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    code_diver_pb2_grpc.add_CodeDiverServiceServicer_to_server(
        CodeDiverGrpcServicer("code-diver.yml"), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()

    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield channel
    finally:
        channel.close()
        server.stop(grace=None)


def test_grpc_info_and_inspection(grpc_channel: grpc.Channel) -> None:
    stub = code_diver_pb2_grpc.CodeDiverServiceStub(grpc_channel)

    # Info
    info_resp = stub.Info(code_diver_pb2.InfoRequest())
    assert info_resp.json_payload
    info_dict = json.loads(info_resp.json_payload)
    assert isinstance(info_dict, dict)

    # Grep
    grep_resp = stub.Grep(
        code_diver_pb2.GrepRequest(
            pattern="CodeDiverGrpcServicer",
            path="src/code_diver/transport",
            limit=10,
        )
    )
    assert len(grep_resp.matches) > 0
    assert any("CodeDiverGrpcServicer" in m.text for m in grep_resp.matches)

    # Tree
    tree_resp = stub.Tree(
        code_diver_pb2.TreeRequest(
            path="src/code_diver/transport",
            depth=2,
            limit=20,
        )
    )
    assert "grpc_server.py" in tree_resp.tree

    # Symbols
    symbols_resp = stub.Symbols(
        code_diver_pb2.SymbolsRequest(
            path="src/code_diver/transport/grpc_server.py",
            limit=50,
        )
    )
    names = [s.name for s in symbols_resp.symbols]
    assert "CodeDiverGrpcServicer" in names


def test_http_remote_indexing(http_client: TestClient) -> None:
    # 1. Ingest files
    ingest_res = http_client.post(
        "/api/v1/index/ingest",
        json={
            "files": [
                {"path": "dummy.py", "content": "def hello_world(): pass\n"}
            ]
        },
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["status"] == "ok"
    assert ingest_res.json()["files_received"] == 1

    # 2. Trigger index
    trig_res = http_client.post(
        "/api/v1/index/trigger",
        json={"repo_path": ".", "clear_existing": False},
    )
    assert trig_res.status_code == 200
    assert trig_res.json()["status"] == "triggered"
    assert "task_id" in trig_res.json()


def test_grpc_remote_ingest(grpc_channel: grpc.Channel) -> None:
    stub = code_diver_pb2_grpc.CodeDiverServiceStub(grpc_channel)

    def chunk_generator():
        yield code_diver_pb2.IngestFileChunk(
            path="remote_test_file.py",
            content=b"class RemoteDemo: pass\n",
            is_last_chunk=True,
        )

    summary = stub.IngestFiles(chunk_generator())
    assert summary.status == "ok"
    assert summary.files_received == 1
    assert summary.total_bytes > 0
