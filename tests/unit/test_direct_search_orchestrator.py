from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.agent import DirectSearchOrchestrator
from code_diver.generation import GenerationResult


pytestmark = pytest.mark.unit


class FakeSearchGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.prompts: list[str] = []

    def generate_json_result(self, prompt: str) -> GenerationResult:
        self.prompts.append(prompt)
        return GenerationResult(
            text=self.responses.pop(0),
            model=self.model,
            input_tokens=7,
            output_tokens=3,
            total_tokens=10,
        )

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text


def test_direct_search_orchestrator_uses_read_only_tools_and_returns_paths(tmp_path: Path) -> None:
    source = tmp_path / "src" / "commands.py"
    source.parent.mkdir()
    source.write_text("def create_command():\n    return 'cmd'\n", encoding="utf-8")
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "search command creation",
                    "tool_calls": [
                        {"name": "code_diver_rg", "arguments": {"pattern": "create_command", "path": "src"}}
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "found command factory",
                    "results": [{"path": "src/commands.py", "startLine": 1, "reason": "factory function"}],
                    "final": "found command creation",
                }
            ),
        ]
    )

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_rg"],
        log_path=log_path,
    ).search(hypothesis_name="rg_only", case_id="case-1", query="where is command created?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/commands.py"]
    assert result.model_calls == 2
    assert result.tool_calls == 1
    assert result.total_tokens == 20
    assert "where is command created?" in provider.prompts[0]

    events = [json.loads(line)["event"] for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert "tool_call" in events
    assert "tool_result" in events
    assert "search_case_completed" in events


def test_direct_search_orchestrator_stages_unscoped_text_probe_after_candidate_tool(tmp_path: Path) -> None:
    candidate = tmp_path / "src" / "candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    unrelated = tmp_path / "other" / "unrelated.py"
    unrelated.parent.mkdir()
    unrelated.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "parallel candidate and probe",
                    "tool_calls": [
                        {"name": "code_diver_h3_search", "arguments": {"query": "target owner", "limit": 10}},
                        {"name": "code_diver_rg", "arguments": {"pattern": "TargetOwner", "limit": 10}},
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "found target",
                    "results": [{"path": "src/candidate.py", "startLine": 1}],
                    "final": "done",
                }
            ),
        ]
    )

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_h3_search", "code_diver_rg"],
        log_path=log_path,
        h3_search_handler=h3_handler,
    ).search(hypothesis_name="agentic_h3", case_id="case-1", query="where is target owner?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/candidate.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    tool_results = [event["payload"] for event in events if event["event"] == "tool_result"]
    assert [payload["name"] for payload in tool_results] == ["code_diver_h3_search", "code_diver_rg"]
    rg_payload = json.loads(tool_results[1]["content"])
    assert rg_payload["metrics"]["scopedToCandidateFiles"] is True
    assert [candidate["path"] for candidate in rg_payload["result"]["candidates"]] == ["src/candidate.py"]


def test_direct_search_orchestrator_stages_unscoped_symbols_after_h3(tmp_path: Path) -> None:
    candidate = tmp_path / "src" / "candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    unrelated = tmp_path / "other" / "unrelated.py"
    unrelated.parent.mkdir()
    unrelated.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "parallel candidate and symbols",
                    "tool_calls": [
                        {"name": "code_diver_h3_search", "arguments": {"query": "target owner", "limit": 10}},
                        {"name": "code_diver_symbols", "arguments": {"query": "TargetOwner", "limit": 10}},
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "found target",
                    "results": [{"path": "src/candidate.py", "startLine": 1}],
                    "final": "done",
                }
            ),
        ]
    )

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_h3_search", "code_diver_symbols"],
        log_path=log_path,
        h3_search_handler=h3_handler,
    ).search(hypothesis_name="agentic_h3", case_id="case-1", query="where is target owner?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/candidate.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    tool_results = [event["payload"] for event in events if event["event"] == "tool_result"]
    assert [payload["name"] for payload in tool_results] == ["code_diver_h3_search", "code_diver_symbols"]
    symbol_payload = json.loads(tool_results[1]["content"])
    assert symbol_payload["metrics"]["scopedToCandidateFiles"] is True
    assert [candidate["path"] for candidate in symbol_payload["result"]["candidates"]] == ["src/candidate.py"]


def test_direct_search_orchestrator_agentic_rejects_probe_path_outside_candidates(tmp_path: Path) -> None:
    candidate = tmp_path / "src" / "candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    unrelated = tmp_path / "other" / "unrelated.py"
    unrelated.parent.mkdir()
    unrelated.write_text("class TargetOwner:\n    pass\n", encoding="utf-8")
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_h3_search", "arguments": {"query": "target owner", "limit": 10}}],
                }
            ),
            json.dumps(
                {
                    "reason": "try outside path",
                    "tool_calls": [{"name": "code_diver_rg", "arguments": {"pattern": "TargetOwner", "path": "other", "limit": 10}}],
                }
            ),
            json.dumps(
                {
                    "reason": "use candidate",
                    "results": [{"path": "src/candidate.py", "startLine": 1}],
                    "final": "done",
                }
            ),
        ]
    )

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [{"path": "src/candidate.py", "score": 0.9}],
            "metrics": {"candidateCount": 1},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_h3_search", "code_diver_rg"],
        log_path=log_path,
        h3_search_handler=h3_handler,
    ).search(hypothesis_name="agentic_h3", case_id="case-1", query="where is target owner?", limit=10)

    assert result.retrieved == ["src/candidate.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    tool_results = [event["payload"] for event in events if event["event"] == "tool_result"]
    rg_payload = json.loads(tool_results[1]["content"])
    assert rg_payload["ok"] is False
    assert "candidate_scope_violation" in rg_payload["error"]


def test_direct_search_orchestrator_caps_read_calls_per_case(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("\n".join(f"line {index}" for index in range(1, 40)), encoding="utf-8")
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "first read batch",
                    "tool_calls": [
                        {
                            "name": "code_diver_read",
                            "arguments": {"file": "src/service.py", "startLine": 1, "lines": 1},
                        }
                        for _ in range(6)
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "second read batch",
                    "tool_calls": [
                        {
                            "name": "code_diver_read",
                            "arguments": {"file": "src/service.py", "startLine": 1, "lines": 1},
                        }
                        for _ in range(6)
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "budget observed",
                    "results": [{"path": "src/service.py", "startLine": 1, "reason": "verified"}],
                    "final": "done",
                }
            ),
        ]
    )

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_read"],
        log_path=log_path,
    ).search(hypothesis_name="read_budget", case_id="case-1", query="where is service?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/service.py"]
    assert result.tool_calls == 12

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    tool_results = [event["payload"] for event in events if event["event"] == "tool_result"]
    assert len(tool_results) == 12
    assert sum(1 for payload in tool_results if payload["ok"]) == DirectSearchOrchestrator.MAX_READ_CALLS
    assert sum(1 for payload in tool_results if not payload["ok"]) == 2
    assert "read_budget_exceeded" in tool_results[-1]["content"]


def test_direct_search_orchestrator_counts_inspect_reads_against_budget(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("line one\n", encoding="utf-8")
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "oversized inspect read batch",
                    "tool_calls": [
                        {
                            "name": "code_diver_inspect",
                            "arguments": {
                                "reads": [
                                    {"file": "src/service.py", "startLine": 1, "lines": 1}
                                    for _ in range(DirectSearchOrchestrator.MAX_READ_CALLS + 1)
                                ]
                            },
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "reason": "budget observed",
                    "results": [{"path": "src/service.py"}],
                    "final": "done",
                }
            ),
        ]
    )

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_inspect"],
        log_path=log_path,
    ).search(hypothesis_name="inspect_budget", case_id="case-1", query="where is service?", limit=10)

    assert result.error is None
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    tool_results = [event["payload"] for event in events if event["event"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["ok"] is False
    assert "read_budget_exceeded" in tool_results[0]["content"]


def test_direct_search_orchestrator_counts_rerank_tool_model_usage(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps(
                {
                    "reason": "rank candidates",
                    "tool_calls": [{"name": "code_diver_rerank", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps(
                {
                    "reason": "use reranked result",
                    "results": [{"path": "src/b.py"}],
                    "final": "done",
                }
            ),
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps(
            [
                {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9},
                {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8},
            ]
        )

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": [candidates[1], candidates[0]],
            "metrics": {
                "modelCalls": 1,
                "model": "rerank-model",
                "inputTokens": 100,
                "outputTokens": 20,
                "totalTokens": 120,
                "estimatedCost": 0.02,
            },
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search", "code_diver_rerank"],
        log_path=log_path,
        search_handler=search_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="rerank_tool", case_id="case-1", query="where is auth?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/b.py", "src/a.py"]
    assert result.model_calls == 4
    assert result.input_tokens == 121
    assert result.output_tokens == 29
    assert result.total_tokens == 150
    assert result.estimated_cost > 0.02
    assert "rerank-model" in result.models


def test_direct_search_orchestrator_forces_rerank_for_rerank_hypothesis(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps(
                {
                    "reason": "premature final",
                    "results": [{"path": "src/a.py"}],
                    "final": "done",
                }
            ),
            json.dumps(
                {
                    "reason": "use forced rerank",
                    "results": [{"path": "src/b.py"}],
                    "final": "done",
                }
            ),
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps(
            [
                {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9},
                {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8},
            ]
        )

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": [candidates[1], candidates[0]],
            "metrics": {"modelCalls": 1, "inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search", "code_diver_rerank"],
        log_path=log_path,
        search_handler=search_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="ai_search_vector_rerank", case_id="case-1", query="where is auth?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/b.py", "src/a.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    forced_calls = [
        event for event in events if event["event"] == "tool_call" and event["payload"]["name"] == "code_diver_rerank"
    ]
    assert len(forced_calls) == 1


def test_direct_search_orchestrator_forces_ephemeral_before_rerank_for_ephemeral_hypothesis(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps(
                {
                    "reason": "tries to skip ephemeral",
                    "tool_calls": [{"name": "code_diver_rerank", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps(
                {
                    "reason": "premature final",
                    "results": [{"path": "src/chunk.py"}],
                    "final": "done",
                }
            ),
            json.dumps(
                {
                    "reason": "use forced rerank",
                    "results": [{"path": "src/chunk.py"}],
                    "final": "done",
                }
            ),
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps([{"id": "file", "path": "src/file.py", "title": "File", "score": 0.9}])

    def ephemeral_handler(query: str, files: list[str], limit: int, args: dict) -> dict:
        assert files == ["src/file.py"]
        return {
            "candidates": [{"id": "chunk", "path": "src/chunk.py", "title": "Chunk", "score": 0.95}],
            "metrics": {"temporaryVectors": 1},
        }

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": [candidate for candidate in candidates if candidate.get("path") == "src/chunk.py"],
            "metrics": {"modelCalls": 1, "inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search", "code_diver_ephemeral_search", "code_diver_rerank"],
        log_path=log_path,
        search_handler=search_handler,
        ephemeral_search_handler=ephemeral_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="h2b_ephemeral_rerank", case_id="case-1", query="where is auth?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/chunk.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    tool_calls = [event["payload"]["name"] for event in events if event["event"] == "tool_call"]
    assert tool_calls == ["code_diver_search", "code_diver_ephemeral_search", "code_diver_rerank"]


def test_direct_search_orchestrator_extends_final_results_with_reranked_candidates(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 3}}],
                }
            ),
            json.dumps(
                {
                    "reason": "rank candidates",
                    "tool_calls": [{"name": "code_diver_rerank", "arguments": {"query": "auth", "limit": 3}}],
                }
            ),
            json.dumps(
                {
                    "reason": "short final",
                    "results": [{"path": "src/b.py"}],
                    "final": "done",
                }
            ),
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps(
            [
                {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9},
                {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8},
                {"id": "c", "path": "src/c.py", "title": "C", "score": 0.7},
            ]
        )

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": [candidates[1], candidates[2], candidates[0]],
            "metrics": {"modelCalls": 1, "inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search", "code_diver_rerank"],
        log_path=log_path,
        search_handler=search_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="ai_search_vector_rerank", case_id="case-1", query="where is auth?", limit=3)

    assert result.error is None
    assert result.retrieved == ["src/b.py", "src/c.py", "src/a.py"]


def test_direct_search_orchestrator_returns_candidates_when_agent_stops_calling_tools(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps({"reason": "invalid empty turn"}),
            json.dumps({"reason": "invalid empty turn"}),
            json.dumps({"reason": "invalid empty turn"}),
            json.dumps({"reason": "invalid empty turn"}),
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps(
            [
                {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9},
                {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8},
            ]
        )

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search"],
        log_path=log_path,
        search_handler=search_handler,
    ).search(hypothesis_name="search_only", case_id="case-1", query="where is auth?", limit=10)

    assert result.error == "agent_returned_no_tool_calls_or_results"
    assert result.retrieved == ["src/a.py", "src/b.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    completed = [event for event in events if event["event"] == "search_case_completed"]
    assert completed[-1]["payload"]["fallback"] == "agent_protocol_error_last_candidates"


def test_direct_search_orchestrator_returns_candidates_when_agent_json_is_invalid(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            "not json",
            "not json",
            "not json",
            "not json",
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps([{"id": "auth", "path": "src/auth.py", "title": "Auth", "score": 0.9}])

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search"],
        log_path=log_path,
        search_handler=search_handler,
    ).search(hypothesis_name="search_only", case_id="case-1", query="where is auth?", limit=10)

    assert result.error == "Agent response did not contain a JSON object."
    assert result.retrieved == ["src/auth.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    completed = [event for event in events if event["event"] == "search_case_completed"]
    assert completed[-1]["payload"]["fallback"] == "exception_last_candidates"


def test_direct_search_orchestrator_retries_invalid_json_response(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            "not json",
            json.dumps({"reason": "repaired final", "results": [{"path": "src/auth.py"}], "final": "done"}),
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps([{"id": "auth", "path": "src/auth.py", "title": "Auth", "score": 0.9}])

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search"],
        log_path=log_path,
        search_handler=search_handler,
    ).search(hypothesis_name="search_only", case_id="case-1", query="where is auth?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/auth.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    retries = [event for event in events if event["event"] == "agent_response_retry"]
    assert retries[-1]["payload"]["reason"] == "invalid_json"


def test_direct_search_orchestrator_requires_adaptive_evidence_before_final(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "premature guess",
                    "results": [{"path": "src/guess.py"}],
                    "final": "done",
                }
            ),
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_search", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps(
                {
                    "reason": "rank candidates",
                    "tool_calls": [{"name": "code_diver_rerank", "arguments": {"query": "auth", "limit": 2}}],
                }
            ),
            json.dumps(
                {
                    "reason": "grounded final",
                    "results": [{"path": "src/auth.py"}],
                    "final": "done",
                }
            ),
        ]
    )

    def search_handler(query: str, limit: int) -> str:
        return json.dumps([{"id": "auth", "path": "src/auth.py", "title": "Auth", "score": 0.9}])

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {"candidates": candidates, "metrics": {"modelCalls": 1, "inputTokens": 1, "outputTokens": 1}}

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_search", "code_diver_rerank"],
        log_path=log_path,
        search_handler=search_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="adaptive_agentic_search", case_id="case-1", query="where is auth?", limit=10)

    assert result.error is None
    assert result.retrieved == ["src/auth.py"]
    events = [json.loads(line)["event"] for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert "adaptive_evidence_required" in events


def test_direct_search_orchestrator_stops_agentic_loop_after_rerank(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_h3_search", "arguments": {"query": "auth handler", "limit": 3}}],
                }
            ),
            json.dumps(
                {
                    "reason": "rerank candidates",
                    "tool_calls": [{"name": "code_diver_rerank", "arguments": {"query": "auth handler", "limit": 3}}],
                }
            ),
            json.dumps(
                {
                    "reason": "would over-search if called",
                    "tool_calls": [{"name": "code_diver_read", "arguments": {"file": "src/a.py"}}],
                }
            ),
        ]
    )

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [
                {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9},
                {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8},
            ],
            "metrics": {"candidateCount": 2},
        }

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": [candidates[1], candidates[0]],
            "metrics": {"modelCalls": 1, "inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_h3_search", "code_diver_rerank", "code_diver_read"],
        log_path=log_path,
        h3_search_handler=h3_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="ai_h3_agentic_test", case_id="case-1", query="where is auth?", limit=3)

    assert result.error is None
    assert result.retrieved == ["src/b.py", "src/a.py"]
    assert result.model_calls == 3
    assert len(provider.prompts) == 2
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    completed = [event for event in events if event["event"] == "search_case_completed"]
    assert completed[-1]["payload"]["fallback"] == "agentic_rerank_early_stop"


def test_direct_search_orchestrator_treats_agent_prefix_as_agentic(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "generate candidates",
                    "tool_calls": [{"name": "code_diver_h3_search", "arguments": {"query": "auth handler", "limit": 3}}],
                }
            ),
            json.dumps(
                {
                    "reason": "rerank candidates",
                    "tool_calls": [{"name": "code_diver_rerank", "arguments": {"query": "auth handler", "limit": 3}}],
                }
            ),
            json.dumps(
                {
                    "reason": "would over-search if called",
                    "tool_calls": [{"name": "code_diver_read", "arguments": {"file": "src/a.py"}}],
                }
            ),
        ]
    )

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        return {
            "candidates": [
                {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9},
                {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8},
            ],
            "metrics": {"candidateCount": 2},
        }

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": [candidates[1], candidates[0]],
            "metrics": {"modelCalls": 1, "inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_h3_search", "code_diver_rerank", "code_diver_read"],
        log_path=log_path,
        h3_search_handler=h3_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="agent_gemma4_e2b_local_rerank", case_id="case-1", query="where is auth?", limit=3)

    assert result.error is None
    assert result.retrieved == ["src/b.py", "src/a.py"]
    assert len(provider.prompts) == 2
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    completed = [event for event in events if event["event"] == "search_case_completed"]
    assert completed[-1]["payload"]["fallback"] == "agentic_rerank_early_stop"


def test_direct_search_orchestrator_monotonic_agent_preserves_h3_baseline_tail(tmp_path: Path) -> None:
    log_path = tmp_path / "search.jsonl"
    provider = FakeSearchGenerationProvider(
        [
            json.dumps(
                {
                    "reason": "try a narrower query",
                    "tool_calls": [{"name": "code_diver_h3_search", "arguments": {"query": "wrong helper", "limit": 3}}],
                }
            ),
            json.dumps(
                {
                    "reason": "rerank narrowed candidates",
                    "tool_calls": [{"name": "code_diver_rerank", "arguments": {"query": "wrong helper", "limit": 3}}],
                }
            ),
        ]
    )

    def h3_handler(query: str, limit: int, args: dict[str, object]) -> dict[str, object]:
        if query == "where is auth?":
            candidates = [
                {"id": "base", "path": "src/auth.py", "title": "Auth", "score": 0.95},
                {"id": "base-helper", "path": "src/session.py", "title": "Session", "score": 0.75},
            ]
        else:
            candidates = [
                {"id": "wrong", "path": "src/wrong.py", "title": "Wrong", "score": 0.9},
            ]
        return {"candidates": candidates, "metrics": {"candidateCount": len(candidates)}}

    def rerank_handler(query: str, candidates: list[dict], limit: int, args: dict) -> dict:
        return {
            "candidates": [
                {"id": "wrong", "path": "src/wrong.py", "title": "Wrong", "score": 0.9},
                {"id": "wrong-2", "path": "src/wrong_2.py", "title": "Wrong 2", "score": 0.8},
                {"id": "wrong-3", "path": "src/wrong_3.py", "title": "Wrong 3", "score": 0.7},
            ],
            "metrics": {"modelCalls": 1, "inputTokens": 10, "outputTokens": 2, "totalTokens": 12},
        }

    result = DirectSearchOrchestrator(
        root=tmp_path,
        generation_provider=provider,
        allowed_tools=["code_diver_h3_search", "code_diver_rerank"],
        log_path=log_path,
        h3_search_handler=h3_handler,
        rerank_handler=rerank_handler,
    ).search(hypothesis_name="agent_gemma4_e4b_monotonic_local_rerank", case_id="case-1", query="where is auth?", limit=3)

    assert result.error is None
    assert result.retrieved == ["src/wrong.py", "src/auth.py", "src/session.py"]
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events].count("monotonic_baseline_seeded") == 1
    completed = [event for event in events if event["event"] == "search_case_completed"]
    assert completed[-1]["payload"]["retrieved"] == ["src/wrong.py", "src/auth.py", "src/session.py"]
