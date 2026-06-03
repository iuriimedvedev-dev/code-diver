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


def test_direct_tool_executor_outline_returns_file_structure_without_bodies(tmp_path: Path) -> None:
    source = tmp_path / "src" / "users.py"
    source.parent.mkdir()
    source.write_text(
        "import os\n\n"
        "class UserController:\n"
        "    def update_user(self, user_id):\n"
        "        return user_id\n",
        encoding="utf-8",
    )

    result = DirectToolExecutor(tmp_path, ["code_diver_outline"]).execute(
        ToolCall("code_diver_outline", {"file": "src/users.py"})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["tool"] == "code_diver_outline"
    assert payload["result"]["imports"] == [{"line": 1, "text": "import os"}]
    assert [symbol["name"] for symbol in payload["result"]["symbols"]] == [
        "UserController",
        "UserController.update_user",
    ]
    assert "return user_id" not in result.content


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
        "code_diver_h3_search",
        "code_diver_tree",
        "code_diver_outline",
        "code_diver_symbols",
        "code_diver_grep",
        "code_diver_rg",
        "code_diver_inspect",
        "code_diver_rerank",
        "code_diver_ephemeral_search",
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


def test_direct_tool_executor_h3_candidates_flow_into_rerank_bank(tmp_path: Path) -> None:
    rerank_seen: list[dict[str, object]] = []

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        assert query == "auth token"
        assert limit == 3
        assert args["profileLimit"] == 40
        return {
            "candidates": [
                {
                    "id": "src/auth.py:10",
                    "path": "src/auth.py",
                    "title": "AuthService",
                    "startLine": 10,
                    "endLine": 20,
                    "score": 0.91,
                    "indexKind": "file_manifest",
                    "source": "h3:balanced",
                }
            ],
            "metrics": {"candidateCount": 1, "source": "h3_manifest_union"},
        }

    def rerank_handler(
        query: str,
        candidates: list[dict[str, object]],
        limit: int,
        args: dict[str, object],
    ) -> dict[str, object]:
        rerank_seen.extend(candidates)
        return {"candidates": candidates[:limit], "metrics": {"candidateCount": len(candidates)}}

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_h3_search", "code_diver_rerank"],
        h3_search_handler=h3_handler,
        rerank_handler=rerank_handler,
    )

    first = executor.execute(
        ToolCall("code_diver_h3_search", {"query": "auth token", "limit": 3, "profileLimit": 40})
    )
    second = executor.execute(ToolCall("code_diver_rerank", {"query": "where auth token?", "limit": 5}))

    assert json.loads(first.content)["ok"] is True
    assert json.loads(second.content)["ok"] is True
    assert [candidate["path"] for candidate in rerank_seen] == ["src/auth.py"]


def test_direct_tool_executor_scopes_unscoped_rg_to_candidate_bank(tmp_path: Path) -> None:
    candidate = tmp_path / "src" / "candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    unrelated = tmp_path / "other" / "unrelated.py"
    unrelated.parent.mkdir()
    unrelated.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    executor = DirectToolExecutor(tmp_path, ["code_diver_h3_search", "code_diver_rg"], h3_search_handler=h3_handler)
    executor.execute(ToolCall("code_diver_h3_search", {"query": "target owner"}))

    result = executor.execute(ToolCall("code_diver_rg", {"pattern": "TargetOwner", "limit": 10}))

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["metrics"]["scopedToCandidateFiles"] is True
    assert payload["metrics"]["scopedFileCount"] == 1
    assert [candidate["path"] for candidate in payload["result"]["candidates"]] == ["src/candidate.py"]
    assert [match["path"] for match in payload["result"]["matches"]] == ["src/candidate.py"]


def test_direct_tool_executor_respects_explicit_rg_path_after_candidate_bank(tmp_path: Path) -> None:
    candidate = tmp_path / "src" / "candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    unrelated = tmp_path / "other" / "unrelated.py"
    unrelated.parent.mkdir()
    unrelated.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    executor = DirectToolExecutor(tmp_path, ["code_diver_h3_search", "code_diver_rg"], h3_search_handler=h3_handler)
    executor.execute(ToolCall("code_diver_h3_search", {"query": "target owner"}))

    result = executor.execute(ToolCall("code_diver_rg", {"pattern": "TargetOwner", "path": "other", "limit": 10}))

    payload = json.loads(result.content)
    assert result.ok is True
    assert "scopedToCandidateFiles" not in payload["metrics"]
    assert [candidate["path"] for candidate in payload["result"]["candidates"]] == ["other/unrelated.py"]


def test_direct_tool_executor_scopes_unscoped_symbols_to_candidate_bank(tmp_path: Path) -> None:
    candidate = tmp_path / "src" / "candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    unrelated = tmp_path / "other" / "unrelated.py"
    unrelated.parent.mkdir()
    unrelated.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_h3_search", "code_diver_symbols"],
        h3_search_handler=h3_handler,
    )
    executor.execute(ToolCall("code_diver_h3_search", {"query": "target owner"}))

    result = executor.execute(ToolCall("code_diver_symbols", {"query": "TargetOwner", "limit": 10}))

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["metrics"]["scopedToCandidateFiles"] is True
    assert payload["metrics"]["scopedFileCount"] == 1
    assert [candidate["path"] for candidate in payload["result"]["candidates"]] == ["src/candidate.py"]
    assert [symbol["path"] for symbol in payload["result"]["symbols"]] == ["src/candidate.py"]


def test_direct_tool_executor_intersects_broad_symbol_directory_with_candidate_bank(tmp_path: Path) -> None:
    candidate = tmp_path / "java" / "src" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    unrelated = tmp_path / "java" / "other" / "unrelated.py"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "java/src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_h3_search", "code_diver_symbols"],
        h3_search_handler=h3_handler,
    )
    executor.execute(ToolCall("code_diver_h3_search", {"query": "target owner"}))

    result = executor.execute(ToolCall("code_diver_symbols", {"path": "java", "query": "TargetOwner", "limit": 10}))

    payload = json.loads(result.content)
    assert result.ok is True
    assert payload["metrics"]["scopedToCandidateFiles"] is True
    assert payload["metrics"]["scopedFileCount"] == 1
    assert payload["metrics"]["scannedFiles"] == 1
    assert [candidate["path"] for candidate in payload["result"]["candidates"]] == ["java/src/candidate.py"]


def test_direct_tool_executor_scopes_inspect_literals_to_candidate_bank(tmp_path: Path) -> None:
    candidate = tmp_path / "src" / "candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("TargetOwner\n", encoding="utf-8")
    unrelated = tmp_path / "other" / "unrelated.py"
    unrelated.parent.mkdir()
    unrelated.write_text("TargetOwner\n", encoding="utf-8")

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_h3_search", "code_diver_inspect"],
        h3_search_handler=h3_handler,
    )
    executor.execute(ToolCall("code_diver_h3_search", {"query": "target owner"}))

    result = executor.execute(
        ToolCall("code_diver_inspect", {"literals": [{"pattern": "TargetOwner", "limit": 10}]})
    )

    payload = json.loads(result.content)
    section = payload["result"]["sections"][0]["result"]
    assert section["metrics"]["scopedToCandidateFiles"] is True
    assert [candidate["path"] for candidate in section["candidates"]] == ["src/candidate.py"]


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


def test_direct_tool_executor_symbols_query_filters_multiline_definition(tmp_path: Path) -> None:
    source = tmp_path / "src" / "users.py"
    source.parent.mkdir()
    source.write_text(
        "class UserController:\n"
        "    def update_user(self, db,\n"
        "                    user_id):\n"
        "        return user_id\n"
        "    def delete_user(self, user_id):\n"
        "        return user_id\n",
        encoding="utf-8",
    )

    result = DirectToolExecutor(tmp_path, ["code_diver_symbols"]).execute(
        ToolCall("code_diver_symbols", {"path": "src/users.py", "query": "update user"})
    )

    payload = json.loads(result.content)
    assert [symbol["name"] for symbol in payload["result"]["symbols"]] == ["UserController.update_user"]


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


def test_direct_tool_executor_rejects_unscoped_symbols_when_candidate_search_is_available(tmp_path: Path) -> None:
    result = DirectToolExecutor(tmp_path, ["code_diver_h3_search", "code_diver_symbols"]).execute(
        ToolCall("code_diver_symbols", {"limit": 100})
    )

    payload = json.loads(result.content)
    assert result.ok is False
    assert payload["ok"] is False
    assert "requires a path or candidate bank" in payload["error"]


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
                "outlines": [{"path": "src/service.py"}],
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
    assert payload["result"]["metrics"] == {"sectionCount": 8, "readCount": 2, "empty": False}
    assert [section["kind"] for section in payload["result"]["sections"]] == [
        "tree",
        "outline",
        "symbols",
        "grep",
        "rg",
        "read",
        "read",
        "read",
    ]
    assert payload["result"]["sections"][1]["result"]["symbols"][0]["name"] == "AuthService"
    assert payload["result"]["sections"][2]["result"]["symbols"][0]["name"] == "AuthService"
    assert payload["result"]["sections"][3]["result"]["candidates"][0]["path"] == "src/service.py"
    assert payload["result"]["sections"][5]["result"]["lines"] == [{"line": 1, "text": "class AuthService:"}]
    assert payload["result"]["sections"][7]["result"]["ok"] is False


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


def test_direct_tool_executor_marks_degraded_rerank_result(tmp_path: Path) -> None:
    def search_handler(query: str, limit: int) -> str:
        return json.dumps([{"id": "a", "path": "src/a.py", "score": 0.9}])

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": candidates[:limit],
            "degraded": True,
            "metrics": {"candidateCount": len(candidates), "errors": 1, "degraded": True, "error": "bad rerank json"},
        }

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_search", "code_diver_rerank"],
        search_handler=search_handler,
        rerank_handler=rerank_handler,
    )

    executor.execute(ToolCall("code_diver_search", {"query": "anything", "limit": 10}))
    result = executor.execute(ToolCall("code_diver_rerank", {"query": "anything", "limit": 10}))

    payload = json.loads(result.content)
    assert result.ok is False
    assert payload["ok"] is False
    assert payload["degraded"] is True
    assert payload["error"] == "bad rerank json"
    assert payload["result"]["candidates"][0]["path"] == "src/a.py"


def test_direct_tool_executor_ephemeral_search_uses_explicit_candidate_files(tmp_path: Path) -> None:
    calls = []

    def handler(query: str, files: list[str], limit: int, args: dict):
        calls.append((query, files, limit, args))
        return {
            "candidates": [{"path": files[0], "startLine": 2, "endLine": 5, "confidence": 0.8}],
            "metrics": {"ephemeral_build_ms": 10.0, "ephemeral_query_ms": 2.0, "temporary_vectors": 12},
        }

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_ephemeral_search"],
        ephemeral_search_handler=handler,
    )

    result = executor.execute(
        ToolCall(
            "code_diver_ephemeral_search",
            {"query": "update user behavior", "files": ["src/users.py", "src/users.py"], "limit": 3},
        )
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert calls[0][0] == "update user behavior"
    assert calls[0][1] == ["src/users.py"]
    assert calls[0][2] == 3
    assert payload["metrics"]["temporary_vectors"] == 12


def test_direct_tool_executor_ephemeral_search_can_use_candidate_bank(tmp_path: Path) -> None:
    def search_handler(query: str, limit: int) -> str:
        return json.dumps([{"id": "a", "path": "src/users.py", "score": 0.9}])

    calls = []

    def ephemeral_handler(query: str, files: list[str], limit: int, args: dict):
        calls.append(files)
        return {"candidates": [{"path": files[0]}], "metrics": {}}

    executor = DirectToolExecutor(
        tmp_path,
        ["code_diver_search", "code_diver_ephemeral_search"],
        search_handler=search_handler,
        ephemeral_search_handler=ephemeral_handler,
    )

    executor.execute(ToolCall("code_diver_search", {"query": "users", "limit": 5}))
    result = executor.execute(ToolCall("code_diver_ephemeral_search", {"query": "update user", "limit": 5}))

    assert json.loads(result.content)["ok"] is True
    assert calls == [["src/users.py"]]


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
