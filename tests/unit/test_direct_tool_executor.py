from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.agent.direct_tool_executor import DirectToolExecutor
from code_diver.agent.tool_call import ToolCall


pytestmark = pytest.mark.unit


def test_direct_tool_executor_returns_structured_rg_without_text_by_default(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class AuthService:\n    def login(self):\n        return True\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_rg"]).execute(
        ToolCall("code_diver_rg", {"pattern": "AuthService|login", "path": "src", "limit": 10})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["tool"] == "code_diver_rg"
    assert payload["metrics"]["matchCount"] == 2
    assert payload["result"]["candidates"][0]["path"] == "src/service.py"
    assert payload["result"]["matches"][0] == {"path": "src/service.py", "line": 1}


def test_direct_tool_executor_read_returns_bounded_source_on_request(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("line one\nline two\nline three\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_read"]).execute(
        ToolCall("code_diver_read", {"file": "src/service.py", "startLine": 2, "lines": 1})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["result"]["path"] == "src/service.py"
    assert payload["result"]["lines"] == [{"line": 2, "text": "line two"}]


def test_direct_tool_executor_manifest_describes_allowed_tools(tmp_path: Path) -> None:
    manifest = DirectToolExecutor(tmp_path, ["code_diver_search", "code_diver_rg", "code_diver_rerank"]).manifest()

    rows = json.loads(manifest)
    assert [row["name"] for row in rows] == ["code_diver_search", "code_diver_rg", "code_diver_rerank"]
    assert rows[0]["parallel_safe"] is True
    assert rows[2]["parallel_safe"] is False
    assert rows[0]["stage"] == "candidate_generation"
    assert "indexKind" in rows[0]["returns"]
    assert "best_for" in rows[1]
    assert rows[2]["stage"] == "ranking"


def test_direct_tool_executor_manifest_all_allowed_tools_have_operational_metadata(tmp_path: Path) -> None:
    allowed = {
        "code_diver_search",
        "code_diver_tree",
        "code_diver_symbols",
        "code_diver_grep",
        "code_diver_rg",
        "code_diver_inspect",
        "code_diver_rerank",
        "code_diver_read",
    }

    rows = json.loads(DirectToolExecutor(tmp_path, sorted(allowed)).manifest())

    assert {row["name"] for row in rows} == allowed
    for row in rows:
        assert row["stage"]
        assert isinstance(row["parallel_safe"], bool)
        assert row["best_for"]
        assert row["avoid_for"]
        assert row["returns"]
        assert row["args"]


def test_direct_tool_executor_tree_uses_gitignore_excludes_and_absolute_path_inside_root(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class Service:\n    pass\n", encoding="utf-8")
    ignored = tmp_path / "ignored" / "hidden.py"
    ignored.parent.mkdir()
    ignored.write_text("class Hidden:\n    pass\n", encoding="utf-8")
    vendor = tmp_path / "vendor" / "dep.py"
    vendor.parent.mkdir()
    vendor.write_text("class Dep:\n    pass\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_tree"], exclude=["vendor/**"]).execute(
        ToolCall("code_diver_tree", {"path": str(source.parent), "depth": 2, "limit": 10})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["result"]["root"] == "src"
    assert [entry["path"] for entry in payload["result"]["entries"]] == ["src/service.py"]
    assert payload["metrics"]["entryCount"] == 1


def test_direct_tool_executor_grep_include_text_and_candidate_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.inspection.grep_service.shutil.which", lambda _: None)
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("AuthService\nother\nAuthService\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_grep"]).execute(
        ToolCall("code_diver_grep", {"pattern": "AuthService", "path": "src", "includeText": True})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["metrics"]["matchCount"] == 2
    assert payload["result"]["matches"][0] == {"path": "src/auth.py", "line": 1, "text": "AuthService"}
    assert payload["result"]["candidates"][0]["startLine"] == 1
    assert payload["result"]["candidates"][0]["endLine"] == 3
    assert payload["result"]["candidates"][0]["evidenceLines"] == [1, 3]


def test_direct_tool_executor_rg_invalid_regex_returns_structured_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.inspection.rg_service.shutil.which", lambda _: None)
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("AuthService\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_rg"]).execute(
        ToolCall("code_diver_rg", {"pattern": "[", "path": "src"})
    )

    payload = json.loads(result.content)
    assert result.ok is False
    assert payload["ok"] is False
    assert payload["tool"] == "code_diver_rg"
    assert payload["metrics"] == {}
    assert payload["error"]


def test_direct_tool_executor_rejects_unscoped_symbols_when_search_is_available(tmp_path: Path) -> None:
    result = DirectToolExecutor(tmp_path, ["code_diver_search", "code_diver_symbols"]).execute(
        ToolCall("code_diver_symbols", {"limit": 100})
    )

    payload = json.loads(result.content)
    assert result.ok is False
    assert payload["ok"] is False
    assert "requires a path" in payload["error"]


def test_direct_tool_executor_rejects_path_escape_at_executor_boundary(tmp_path: Path) -> None:
    result = DirectToolExecutor(tmp_path, ["code_diver_read"]).execute(
        ToolCall("code_diver_read", {"file": "../secret.txt"})
    )

    payload = json.loads(result.content)
    assert result.ok is False
    assert payload["ok"] is False
    assert "escapes repository root" in payload["error"]


def test_direct_tool_executor_caps_inspect_reads(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("line one\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_inspect"], max_inspect_reads=1).execute(
        ToolCall(
            "code_diver_inspect",
            {"reads": [{"file": "src/service.py"}, {"file": "src/service.py"}]},
        )
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["result"]["metrics"]["readCount"] == 1
    assert payload["result"]["sections"][1]["result"]["error"].startswith("inspect_read_budget_exceeded")


def test_direct_tool_executor_inspect_batches_mixed_sections_and_counts_budgeted_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_diver.inspection.grep_service.shutil.which", lambda _: None)
    monkeypatch.setattr("code_diver.inspection.rg_service.shutil.which", lambda _: None)
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class AuthService:\n    def login(self):\n        return 'token'\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_inspect"], max_inspect_reads=2).execute(
        ToolCall(
            "code_diver_inspect",
            {
                "trees": [{"path": "src", "depth": 1, "limit": 5}],
                "symbols": [{"path": "src/service.py", "limit": 5}],
                "literals": [{"pattern": "AuthService", "path": "src", "limit": 5}],
                "regexes": [{"pattern": "login|token", "path": "src", "limit": 5}],
                "reads": [
                    {"file": "src/service.py", "startLine": 1, "lines": 1},
                    {"path": "src/service.py", "start_line": 2, "lines": 1},
                    {"file": "src/service.py", "startLine": 3, "lines": 1},
                ],
            },
        )
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["result"]["metrics"] == {"sectionCount": 7, "readCount": 2, "empty": False}
    assert [section["kind"] for section in payload["result"]["sections"]] == [
        "tree",
        "symbols",
        "grep",
        "rg",
        "read",
        "read",
        "read",
    ]
    assert payload["result"]["sections"][1]["result"]["symbols"][0]["name"] == "AuthService"
    assert payload["result"]["sections"][2]["result"]["candidates"][0]["path"] == "src/service.py"
    assert payload["result"]["sections"][4]["result"]["lines"] == [{"line": 1, "text": "class AuthService:"}]
    assert payload["result"]["sections"][6]["result"]["ok"] is False


def test_direct_tool_executor_reranks_previous_search_candidates(tmp_path: Path) -> None:
    def search_handler(query: str, limit: int) -> str:
        return json.dumps(
            [
                {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9, "indexKind": "symbol"},
                {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8, "indexKind": "symbol"},
            ]
        )

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        assert query == "where is auth?"
        assert [candidate["id"] for candidate in candidates] == ["a", "b"]
        return {
            "candidates": [candidates[1], candidates[0]],
            "metrics": {
                "candidateCount": 2,
                "returnedCount": 2,
                "modelCalls": 1,
                "inputTokens": 10,
                "outputTokens": 2,
                "totalTokens": 12,
                "estimatedCost": 0.01,
            },
        }

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_search", "code_diver_rerank"],
        search_handler=search_handler,
        rerank_handler=rerank_handler,
    )

    search = executor.execute(ToolCall("code_diver_search", {"query": "auth", "limit": 2}))
    rerank = executor.execute(ToolCall("code_diver_rerank", {"query": "where is auth?", "limit": 2}))

    assert json.loads(search.content)["result"]["metrics"]["candidateCount"] == 2
    payload = json.loads(rerank.content)
    assert payload["ok"] is True
    assert [candidate["path"] for candidate in payload["result"]["candidates"]] == ["src/b.py", "src/a.py"]
    assert payload["metrics"]["modelCalls"] == 1


@pytest.mark.parametrize("raw_response", ["not json", json.dumps({"path": "src/a.py"})])
def test_direct_tool_executor_search_handler_invalid_payload_returns_empty_candidates(
    tmp_path: Path,
    raw_response: str,
) -> None:
    def search_handler(query: str, limit: int) -> str:
        return raw_response

    result = DirectToolExecutor(
        tmp_path,
        ["code_diver_search"],
        search_handler=search_handler,
    ).execute(ToolCall("code_diver_search", {"query": "auth", "limit": 5}))

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["result"]["candidates"] == []
    assert payload["metrics"] == {"candidateCount": 0, "source": "vector"}


def test_direct_tool_executor_rejects_search_when_handler_is_missing(tmp_path: Path) -> None:
    result = DirectToolExecutor(tmp_path, ["code_diver_search"]).execute(
        ToolCall("code_diver_search", {"query": "auth", "limit": 5})
    )

    payload = json.loads(result.content)
    assert result.ok is False
    assert payload["ok"] is False
    assert "not available without a search handler" in payload["error"]


def test_direct_tool_executor_rerank_filters_candidate_ids_and_deduplicates_bank(tmp_path: Path) -> None:
    def search_handler(query: str, limit: int) -> str:
        return json.dumps(
            [
                {"id": "a", "path": "src/a.py", "score": 0.9},
                {"id": "a", "path": "src/a.py", "score": 0.8},
                {"id": "b", "path": "src/b.py", "score": 0.7},
                {"path": "src/c.py", "startLine": 12, "score": 0.6},
            ]
        )

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        assert [candidate.get("id") or candidate["path"] for candidate in candidates] == ["b", "src/c.py"]
        return {"candidates": candidates[:limit], "metrics": {"candidateCount": len(candidates), "modelCalls": 1}}

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_search", "code_diver_rerank"],
        search_handler=search_handler,
        rerank_handler=rerank_handler,
    )

    executor.execute(ToolCall("code_diver_search", {"query": "anything", "limit": 10}))
    result = executor.execute(
        ToolCall("code_diver_rerank", {"query": "anything", "candidateIds": ["b", "src/c.py"], "limit": 10})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["metrics"]["candidateCount"] == 2


def test_direct_tool_executor_reranks_candidates_from_batched_inspect(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class AuthService:\n    def login(self):\n        return True\n", encoding="utf-8")

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        assert candidates
        assert candidates[0]["path"] == "src/service.py"
        return {"candidates": candidates[:limit], "metrics": {"modelCalls": 1}}

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_inspect", "code_diver_rerank"],
        rerank_handler=rerank_handler,
    )

    executor.execute(
        ToolCall(
            "code_diver_inspect",
            {"regexes": [{"pattern": "AuthService|login", "path": "src", "limit": 10}]},
        )
    )
    rerank = executor.execute(ToolCall("code_diver_rerank", {"query": "where is auth?", "limit": 1}))

    payload = json.loads(rerank.content)
    assert payload["ok"] is True
    assert payload["result"]["candidates"][0]["path"] == "src/service.py"
