import json
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock

from code_diver.acp.server import AcpServer
from code_diver.domain import CodeItem, CodeItemIndexKind, SearchResult


def test_acp_initialize() -> None:
    server = AcpServer("code-diver.yml")
    responses = []
    server._write_message = lambda payload: responses.append(payload)

    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "clientCapabilities": {"terminal": True},
            "clientInfo": {"name": "zed", "version": "0.1.0"},
        },
    }
    server.process_message(json.dumps(msg))

    assert len(responses) == 1
    resp = responses[0]
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == 1
    assert resp["result"]["agentInfo"]["name"] == "code-diver"
    assert resp["result"]["agentCapabilities"]["promptCapabilities"]["embeddedContext"] is True


def test_acp_session_lifecycle() -> None:
    server = AcpServer("code-diver.yml")
    responses = []
    server._write_message = lambda payload: responses.append(payload)

    # 1. session/new
    new_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "session/new",
        "params": {"cwd": "/tmp/test", "mcpServers": []},
    }
    server.process_message(json.dumps(new_req))

    assert len(responses) == 1
    session_id = responses[0]["result"]["sessionId"]
    assert session_id.startswith("sess_")
    assert session_id in server._sessions

    # 2. session/close
    close_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "session/close",
        "params": {"sessionId": session_id},
    }
    server.process_message(json.dumps(close_req))

    assert len(responses) == 2
    assert responses[1]["id"] == 3
    assert session_id not in server._sessions


def test_acp_session_prompt_execution() -> None:
    server = AcpServer("code-diver.yml")
    messages = []
    server._write_message = lambda payload: messages.append(payload)

    # Mock runtime to avoid loading model / vector store in unit test
    fake_item = CodeItem(
        id="item_001",
        path="src/main.rs",
        start_line=1,
        end_line=20,
        content="fn main() {\n    println!(\"hello\");\n}",
        title="main function",
        metadata={"index_kind": CodeItemIndexKind.SYMBOL_CHUNK},
    )
    fake_result = SearchResult(item=fake_item, score=0.92)

    fake_config = MagicMock()
    fake_config.root = "/test/repo"
    fake_runtime = MagicMock()
    fake_runtime.base_strategy.search.return_value = [fake_result]

    server.get_runtime = lambda: (fake_config, fake_runtime)

    # Create session
    server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "session/new",
                "params": {"cwd": "/test/repo"},
            }
        )
    )
    session_id = messages[0]["result"]["sessionId"]

    # Send prompt
    server.process_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": "where is main defined"}],
                },
            }
        )
    )

    # Wait for turn execution thread to finish
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if any(m.get("id") == 11 for m in messages):
            break
        time.sleep(0.02)

    # Validate messages streamed
    notifications = [m for m in messages if "method" in m and m["method"] == "session/update"]
    assert len(notifications) >= 4  # plan, tool_call, tool_call_update, agent_message_chunk, plan_update

    # Validate final response
    prompt_resp = next(m for m in messages if m.get("id") == 11)
    assert prompt_resp["result"]["stopReason"] == "end_turn"
