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
