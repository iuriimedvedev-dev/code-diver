import json
from pathlib import Path

from code_diver.mcp.server import create_mcp_server


def test_mcp_server_tools_registered() -> None:
    server = create_mcp_server("code-diver.yml")
    assert server.name == "code-diver"
    tools = server._tool_manager.list_tools() if hasattr(server, "_tool_manager") else []
    tool_names = [t.name for t in tools]
    assert "code_diver_search" in tool_names
    assert "code_diver_info" in tool_names
    assert "code_diver_read" in tool_names
    assert "code_diver_grep" in tool_names
    assert "code_diver_symbols" in tool_names
    assert "code_diver_tree" in tool_names
    assert "code_diver_submit_agent_search" in tool_names
    assert "code_diver_task_status" in tool_names
    assert "code_diver_task_result" in tool_names
    assert "code_diver_task_cancel" in tool_names
    assert "code_diver_tasks_list" in tool_names


def test_mcp_server_info_tool(tmp_path: Path) -> None:
    cfg_file = tmp_path / "test-config.yml"
    cfg_file.write_text(
        f"""
root: {tmp_path}
artifact: {tmp_path}/index.json
storage:
  provider: json
""",
        encoding="utf-8",
    )
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "openai_compatible",
                "model": "test-model",
                "dimensions": 10,
                "items": [],
            }
        ),
        encoding="utf-8",
    )

    server = create_mcp_server(cfg_file)
    # Call info tool function directly
    tool_entry = server._tool_manager._tools["code_diver_info"]
    result_str = tool_entry.fn()
    payload = json.loads(result_str)
    assert payload["store"]["provider"] == "json"
    assert payload["store"]["items_count"] == 0


def test_mcp_server_task_lifecycle(tmp_path: Path, monkeypatch) -> None:
    cfg_file = tmp_path / "test-config.yml"
    cfg_file.write_text(
        f"""
root: {tmp_path}
artifact: {tmp_path}/index.json
storage:
  provider: json
""",
        encoding="utf-8",
    )
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "openai_compatible",
                "model": "test-model",
                "dimensions": 10,
                "items": [],
            }
        ),
        encoding="utf-8",
    )

    class DummyStore:
        def metadata(self):
            return {}

        def close(self):
            return None

    class DummyStrategy:
        def search(self, query, limit):
            return []

    monkeypatch.setattr("code_diver.runtime.search_runtime.create_vector_store", lambda cfg: DummyStore())
    monkeypatch.setattr(
        "code_diver.providers.embedding_provider_builder.make_embedding_provider",
        lambda cfg, metadata=None: object(),
    )
    monkeypatch.setattr(
        "code_diver.strategies.retrieval_strategy_factory.RetrievalStrategyFactory.create",
        lambda self, strategy_id, config, provider, vector_store: DummyStrategy(),
    )

    server = create_mcp_server(cfg_file)
    tools = server._tool_manager._tools

    # 1. Submit search task
    submit_str = tools["code_diver_submit_agent_search"].fn(query="test", limit=5)
    submit_res = json.loads(submit_str)
    assert "task_id" in submit_res
    task_id = submit_res["task_id"]
    assert submit_res["status"] == "working"

    # 2. Check status (may be working or completed quickly)
    import time

    time.sleep(0.1)
    status_str = tools["code_diver_task_status"].fn(task_id=task_id)
    status_res = json.loads(status_str)
    assert status_res["task_id"] == task_id
    assert status_res["status"] in ("working", "completed")

    # 3. Check result once completed
    time.sleep(0.2)
    result_str = tools["code_diver_task_result"].fn(task_id=task_id)
    result_res = json.loads(result_str)
    assert result_res["status"] == "completed"
    assert "items" in result_res["result"]

    # 4. List tasks
    list_str = tools["code_diver_tasks_list"].fn(limit=10)
    list_res = json.loads(list_str)
    assert len(list_res) >= 1
    assert any(t["task_id"] == task_id for t in list_res)

