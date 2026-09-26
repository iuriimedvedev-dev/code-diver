"""End-to-end tests for Code Diver remote server and unified client."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import grpc
import httpx2
import pytest

from code_diver.transport.client import RemoteCodeDiverClient
from code_diver.transport.grpc_gen import mcp_service_pb2, mcp_service_pb2_grpc


@pytest.fixture(scope="module")
def remote_server():
    """Start `code-diver serve` process on dynamic/test ports."""
    http_port = 18080
    grpc_port = 55051
    cmd = [
        sys.executable,
        "-c",
        f"from code_diver.cli import main; main(['serve', '--http-port', '{http_port}', '--grpc-port', '{grpc_port}', 'code-diver.yml'])",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Poll /health until server responds
    deadline = time.time() + 15
    healthy = False
    while time.time() < deadline:
        try:
            with httpx2.Client() as client:
                res = client.get(f"http://127.0.0.1:{http_port}/health", timeout=1.0)
                if res.status_code == 200:
                    healthy = True
                    break
        except Exception:
            time.sleep(0.5)

    if not healthy:
        proc.kill()
        out, err = proc.communicate()
        raise RuntimeError(f"Server failed to start:\nstdout: {out}\nstderr: {err}")

    yield {"http_url": f"http://127.0.0.1:{http_port}", "grpc_addr": f"127.0.0.1:{grpc_port}"}

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_e2e_http_health_and_info(remote_server):
    url = remote_server["http_url"]
    with httpx2.Client(timeout=30.0) as client:
        health = client.get(f"{url}/health").json()
        assert health["status"] == "ok"
        assert health["version"] == "0.4.3"

        info = client.get(f"{url}/api/v1/info").json()
        assert isinstance(info, dict)


def test_e2e_remote_client_http_operations(remote_server):
    client = RemoteCodeDiverClient(http_url=remote_server["http_url"])
    try:
        # Ingest files
        res = client.ingest_files_http(
            [
                {"path": "e2e_remote_test.py", "content": "class RemoteE2E: pass\n"}
            ]
        )
        assert res["status"] == "ok"
        assert res["files_received"] == 1

        # Trigger remote index
        trig = client.trigger_remote_index_http(clear_existing=False)
        assert trig["status"] == "triggered"
        assert "task_id" in trig
    finally:
        client.close()


def test_e2e_remote_client_grpc_operations(remote_server):
    client = RemoteCodeDiverClient(
        http_url=remote_server["http_url"],
        grpc_addr=remote_server["grpc_addr"],
    )
    try:
        # Ingest via gRPC
        summary = client.ingest_files_grpc(
            [("e2e_grpc_file.py", b"def grpc_hello(): pass\n")]
        )
        assert summary.status == "ok"
        assert summary.files_received == 1

        # Trigger index streaming
        updates = list(client.trigger_index_grpc(clear_existing=False))
        assert len(updates) > 0
        stages = [u.stage for u in updates]
        assert "init" in stages
    finally:
        client.close()


def test_e2e_http_mcp_jsonrpc(remote_server):
    url = remote_server["http_url"]
    with httpx2.Client(timeout=30.0) as client:
        # POST {url}/mcp with 'initialize' -> verify protocolVersion == '2024-11-05'
        init_res = client.post(
            f"{url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert init_res.status_code == 200
        init_data = init_res.json()
        assert init_data["result"]["protocolVersion"] == "2024-11-05"

        # POST {url}/mcp with 'tools/list' -> verify tools list contains code_diver_search, code_diver_grep, etc.
        tools_res = client.post(
            f"{url}/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools_res.status_code == 200
        tools_data = tools_res.json()
        tool_names = [t["name"] for t in tools_data["result"]["tools"]]
        for tool in ["code_diver_search", "code_diver_grep", "code_diver_read", "code_diver_symbols", "code_diver_tree", "code_diver_info"]:
            assert tool in tool_names

        # POST {url}/mcp with 'tools/call' for 'code_diver_info' -> verify content text is valid json
        call_res = client.post(
            f"{url}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "code_diver_info", "arguments": {}},
            },
        )
        assert call_res.status_code == 200
        call_data = call_res.json()
        assert not call_data["result"].get("isError", False)
        content_text = call_data["result"]["content"][0]["text"]
        info_json = json.loads(content_text)
        assert isinstance(info_json, dict)

        # POST {url}/ with 'tools/list' -> verify root path also works as MCP endpoint
        root_res = client.post(
            f"{url}/",
            json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
        )
        assert root_res.status_code == 200
        root_data = root_res.json()
        root_tool_names = [t["name"] for t in root_data["result"]["tools"]]
        assert "code_diver_search" in root_tool_names
        assert "code_diver_grep" in root_tool_names


def test_e2e_knotgate_grpc_mcpservice(remote_server):
    with grpc.insecure_channel(remote_server["grpc_addr"]) as channel:
        stub = mcp_service_pb2_grpc.MCPServiceStub(channel)

        # Call ListTools -> verify response.success is True and tools length >= 6
        list_resp = stub.ListTools(mcp_service_pb2.ListToolsRequest())
        assert list_resp.response.success is True
        assert len(list_resp.tools) >= 6

        # Call CallTool for 'code_diver_tree' with arguments={'path': 'src/code_diver/transport'} -> verify result.content[0].text contains files
        tree_resp = stub.CallTool(
            mcp_service_pb2.CallToolRequest(
                tool_name="code_diver_tree",
                arguments={"path": "src/code_diver/transport"},
            )
        )
        assert tree_resp.response.success is True
        assert not tree_resp.result.is_error
        assert len(tree_resp.result.content) > 0
        tree_text = tree_resp.result.content[0].text
        assert "knotgate_servicer.py" in tree_text or "http_server.py" in tree_text

        # Call GetHealth -> verify health.status == 'healthy'
        health_resp = stub.GetHealth(mcp_service_pb2.GetHealthRequest(include_metrics=True))
        assert health_resp.response.success is True
        assert health_resp.health.status == "healthy"

        # Call GetCapabilities -> verify capabilities.service_name == 'code-diver'
        cap_resp = stub.GetCapabilities(mcp_service_pb2.GetCapabilitiesRequest())
        assert cap_resp.response.success is True
        assert cap_resp.capabilities.service_name == "code-diver"

