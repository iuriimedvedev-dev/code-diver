from __future__ import annotations

import json

import pytest

from code_diver.agent.rerank_tool_handler import RerankToolHandler
from code_diver.config.llm_rerank_config import LlmRerankConfig
from code_diver.generation import GenerationResult


pytestmark = pytest.mark.unit


class FakeGenerationProvider:
    name = "fake"
    model = "fake-rerank"

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def generate_json_result(self, prompt: str) -> GenerationResult:
        self.prompts.append(prompt)
        return GenerationResult(
            text=self.response,
            model=self.model,
            input_tokens=50,
            output_tokens=5,
            total_tokens=55,
        )

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text


def test_rerank_tool_handler_returns_ranked_structured_candidates() -> None:
    provider = FakeGenerationProvider(json.dumps({"results": [{"index": 2, "confidence": 0.9}]}))
    handler = RerankToolHandler(provider, LlmRerankConfig(candidate_limit=3, include_reasons=False))

    payload = handler.rerank(
        "where is auth handled?",
        [
            {"id": "a", "path": "src/a.py", "title": "A", "score": 0.9, "preview": "misc"},
            {"id": "b", "path": "src/b.py", "title": "B", "score": 0.8, "preview": "auth handler"},
        ],
        2,
        {"mode": "compact"},
    )

    assert [candidate["path"] for candidate in payload["candidates"]] == ["src/b.py", "src/a.py"]
    assert payload["candidates"][0]["confidence"] == 0.9
    assert payload["selectedIndices"] == [2]
    assert payload["metrics"]["modelCalls"] == 1
    assert payload["metrics"]["inputTokens"] == 50
    assert "auth handler" in provider.prompts[0]


def test_rerank_tool_handler_deduplicates_limits_and_ignores_invalid_model_indices() -> None:
    provider = FakeGenerationProvider(
        json.dumps(
            {
                "results": [
                    {"index": 3, "confidence": 0.99},
                    {"index": 1, "confidence": 0.7},
                    {"index": 99, "confidence": 1.0},
                    {"index": 1, "confidence": 0.1},
                    {"index": "bad", "confidence": 1.0},
                ]
            }
        )
    )
    handler = RerankToolHandler(provider, LlmRerankConfig(candidate_limit=3, include_reasons=False))

    payload = handler.rerank(
        "find command handler",
        [
            {"id": "a", "path": "src/a.py", "score": "0.9"},
            {"id": "a", "path": "src/a.py", "score": "0.8"},
            {"path": "src/b.py", "startLine": 10, "score": None},
            {"id": "c", "path": "src/c.py", "score": 0.1},
            {"id": "d", "path": "src/d.py", "score": 0.0},
        ],
        3,
        {},
    )

    assert [candidate["path"] for candidate in payload["candidates"]] == ["src/c.py", "src/a.py", "src/b.py"]
    assert payload["selectedIndices"] == [3, 1]
    assert payload["candidates"][0]["confidence"] == 0.99
    assert payload["candidates"][1]["confidence"] == 0.7
    assert payload["candidates"][2]["rerankRank"] == 3
    assert payload["metrics"]["candidateCount"] == 3


def test_rerank_tool_handler_invalid_json_falls_back_to_input_order() -> None:
    provider = FakeGenerationProvider("not json")
    handler = RerankToolHandler(provider, LlmRerankConfig(candidate_limit=10))

    payload = handler.rerank(
        "where is auth?",
        [
            {"id": "a", "path": "src/a.py", "score": 0.9},
            {"id": "b", "path": "src/b.py", "score": 0.8},
        ],
        2,
        {},
    )

    assert [candidate["path"] for candidate in payload["candidates"]] == ["src/a.py", "src/b.py"]
    assert payload["selectedIndices"] == []
    assert [candidate["rerankRank"] for candidate in payload["candidates"]] == [1, 2]
    assert payload["metrics"]["modelCalls"] == 1
    assert payload["degraded"] is True
    assert payload["fallback"] == "input_order"
    assert payload["metrics"]["degraded"] is True
    assert payload["metrics"]["errors"] == 1
    assert "JSON response" in payload["metrics"]["error"]


def test_rerank_tool_handler_applies_runtime_mode_reason_and_preview_overrides() -> None:
    provider = FakeGenerationProvider(json.dumps({"results": [{"index": 1, "confidence": 0.8, "reason": "owns route"}]}))
    handler = RerankToolHandler(provider, LlmRerankConfig(candidate_limit=10, include_reasons=False, max_preview_chars=50))

    payload = handler.rerank(
        "where is the login route?",
        [
            {
                "id": "route",
                "path": "src/routes.py",
                "title": "routes",
                "score": 0.7,
                "preview": " ".join(["login route owner"] * 20),
            }
        ],
        1,
        {"mode": "precision", "includeReasons": True, "maxPreviewChars": 24, "candidateLimit": 1},
    )

    prompt = provider.prompts[0]
    assert "Optimize rank 1" in prompt
    assert '"reason": "short reason"' in prompt
    assert "login route owner login..." in prompt
    assert payload["candidates"][0]["rerankReason"] == "owns route"
    assert payload["metrics"]["mode"] == "precision"


def test_rerank_tool_handler_marks_path_roles_for_small_local_rankers() -> None:
    provider = FakeGenerationProvider(json.dumps({"results": [{"index": 2, "confidence": 0.9}]}))
    handler = RerankToolHandler(provider, LlmRerankConfig(candidate_limit=3, include_reasons=False))

    payload = handler.rerank(
        "where is auth implemented?",
        [
            {"id": "test", "path": "src/tests/test_auth.py", "score": 0.9},
            {"id": "impl", "path": "src/auth.py", "score": 0.8},
            {"id": "doc", "path": "README.md", "score": 0.7},
        ],
        2,
        {},
    )

    prompt = provider.prompts[0]
    assert '"path_role": "test"' in prompt
    assert '"path_role": "implementation"' in prompt
    assert '"path_role": "doc"' in prompt
    assert "Tests/examples/docs can support evidence" in prompt
    assert payload["candidates"][0]["path_role"] == "implementation"


def test_rerank_tool_handler_empty_or_pathless_candidates_skip_model_call() -> None:
    provider = FakeGenerationProvider(json.dumps({"results": [{"index": 1, "confidence": 1.0}]}))
    handler = RerankToolHandler(provider, LlmRerankConfig())

    payload = handler.rerank("anything", [{"score": 1.0}, "bad"], 5, {})

    assert payload == {"candidates": [], "metrics": {"candidateCount": 0, "returnedCount": 0}}
    assert provider.prompts == []
