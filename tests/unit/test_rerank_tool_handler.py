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
