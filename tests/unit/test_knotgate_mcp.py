"""Unit tests for Knotgate MCPService (gRPC) and standard HTTP MCP endpoints."""

from __future__ import annotations

import json
from collections.abc import Generator
from concurrent import futures

import grpc
import pytest
from starlette.testclient import TestClient

from code_diver.transport.grpc_gen import mcp_service_pb2, mcp_service_pb2_grpc
from code_diver.transport.http_server import create_remote_app
from code_diver.transport.knotgate_servicer import KnotgateMcpServiceServicer


@pytest.fixture
def http_client() -> TestClient:
    app = create_remote_app("code-diver.yml")
    return TestClient(app)


@pytest.fixture(scope="module")
def grpc_channel() -> Generator[grpc.Channel, None, None]:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    mcp_service_pb2_grpc.add_MCPServiceServicer_to_server(
        KnotgateMcpServiceServicer("code-diver.yml"), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()

    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield channel
    finally:
        channel.close()
        server.stop(grace=None)


def test_knotgate_grpc_list_tools(grpc_channel: grpc.Channel) -> None:
    stub = mcp_service_pb2_grpc.MCPServiceStub(grpc_channel)
    resp = stub.ListTools(mcp_service_pb2.ListToolsRequest())
    assert resp.response.success
    tool_names = [tool.name for tool in resp.tools]
    expected_tools = [
        "code_diver_search",
        "code_diver_grep",
        "code_diver_read",
        "code_diver_symbols",
        "code_diver_tree",
        "code_diver_info",
    ]
    for expected in expected_tools:
        assert expected in tool_names


def test_knotgate_grpc_call_tool_info(grpc_channel: grpc.Channel) -> None:
    stub = mcp_service_pb2_grpc.MCPServiceStub(grpc_channel)
    resp = stub.CallTool(mcp_service_pb2.CallToolRequest(tool_name="code_diver_info"))
    assert resp.response.success
    assert not resp.result.is_error
    assert len(resp.result.content) > 0
    assert resp.result.content[0].type == "text"
    info_data = json.loads(resp.result.content[0].text)
    assert isinstance(info_data, dict)
    assert "vector_store" in info_data or "strategy" in info_data or "root" in info_data


def test_knotgate_grpc_call_tool_tree(grpc_channel: grpc.Channel) -> None:
    stub = mcp_service_pb2_grpc.MCPServiceStub(grpc_channel)
    resp = stub.CallTool(
        mcp_service_pb2.CallToolRequest(
            tool_name="code_diver_tree",
            arguments={"path": "src/code_diver/transport"},
        )
    )
    assert resp.response.success
    assert not resp.result.is_error
    assert len(resp.result.content) > 0
    tree_text = resp.result.content[0].text
    assert "knotgate_servicer.py" in tree_text or "http_server.py" in tree_text


def test_knotgate_grpc_call_tool_grep(grpc_channel: grpc.Channel) -> None:
    stub = mcp_service_pb2_grpc.MCPServiceStub(grpc_channel)
    resp = stub.CallTool(
        mcp_service_pb2.CallToolRequest(
            tool_name="code_diver_grep",
            arguments={
                "pattern": "KnotgateMcpServiceServicer",
                "path": "src/code_diver/transport",
            },
        )
    )
    assert resp.response.success
    assert not resp.result.is_error
    assert len(resp.result.content) > 0
    matches = json.loads(resp.result.content[0].text)
    assert len(matches) > 0
    assert any("KnotgateMcpServiceServicer" in m["text"] for m in matches)


def test_knotgate_grpc_get_health(grpc_channel: grpc.Channel) -> None:
    stub = mcp_service_pb2_grpc.MCPServiceStub(grpc_channel)
    resp = stub.GetHealth(mcp_service_pb2.GetHealthRequest(include_metrics=True))
    assert resp.response.success
    assert resp.health.status == "healthy"
    assert resp.metrics is not None
    assert resp.metrics.total_calls >= 0
    assert resp.metrics.uptime_seconds >= 0


def test_knotgate_grpc_get_capabilities(grpc_channel: grpc.Channel) -> None:
    stub = mcp_service_pb2_grpc.MCPServiceStub(grpc_channel)
    resp = stub.GetCapabilities(mcp_service_pb2.GetCapabilitiesRequest())
    assert resp.response.success
    assert resp.capabilities.service_name == "code-diver"
    features = list(resp.capabilities.supported_features)
    assert "search" in features
    assert "grep" in features
    assert "read" in features
    assert "symbols" in features
    assert "tree" in features
    assert "info" in features


def test_http_mcp_initialize(http_client: TestClient) -> None:
    res = http_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    result = data["result"]
    assert "protocolVersion" in result
    assert "capabilities" in result


def test_http_mcp_tools_list(http_client: TestClient) -> None:
    res = http_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["jsonrpc"] == "2.0"
    tools = data["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "code_diver_search" in tool_names
    assert "code_diver_grep" in tool_names
    assert "code_diver_read" in tool_names
    assert "code_diver_symbols" in tool_names
    assert "code_diver_tree" in tool_names
    assert "code_diver_info" in tool_names


def test_http_mcp_tools_call_info(http_client: TestClient) -> None:
    res = http_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "code_diver_info", "arguments": {}},
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["jsonrpc"] == "2.0"
    assert not data["result"]["isError"]
    content = data["result"]["content"]
    assert len(content) > 0
    info_json = json.loads(content[0]["text"])
    assert isinstance(info_json, dict)


def test_http_root_tools_list(http_client: TestClient) -> None:
    res = http_client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["jsonrpc"] == "2.0"
    tools = data["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "code_diver_info" in tool_names
