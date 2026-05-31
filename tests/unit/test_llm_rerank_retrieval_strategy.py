from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.generation import GenerationResult
from code_diver.strategies.llm_rerank_retrieval_strategy import LlmRerankRetrievalStrategy
from code_diver.strategies.llm_rerank_response_parser import LlmRerankResponseParser
from code_diver.tracing import TraceLogger


pytestmark = pytest.mark.unit


class FakeStrategy:
    def __init__(self, results: list[SearchResult]):
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.results[:limit]


class FakeGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def generate_json(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response

    def generate_json_result(self, prompt: str) -> GenerationResult:
        self.prompts.append(prompt)
        return GenerationResult(
            text=self.response,
            model=self.model,
            input_tokens=100,
            output_tokens=10,
            total_tokens=110,
        )


def test_llm_rerank_reorders_candidates_and_preserves_fallbacks(tmp_path: Path) -> None:
    results = [
        _result("a", "src/a.py", 0.9),
        _result("b", "src/b.py", 0.8),
        _result("c", "src/c.py", 0.7),
    ]
    trace_path = tmp_path / "trace.jsonl"
    strategy = LlmRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeGenerationProvider('{"results":[{"index":3,"confidence":0.9,"reason":"best"}]}'),
        candidate_limit=3,
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=True)),
    )

    reranked = strategy.search("where is auth handled", 2)

    assert [result.item.path for result in reranked] == ["src/c.py", "src/a.py"]
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == ["llm_rerank_prompt", "llm_rerank_response"]
    assert records[1]["payload"]["selected_indices"] == [3]
    assert records[1]["payload"]["total_tokens"] == 110


def test_llm_rerank_falls_back_to_base_order_on_bad_json() -> None:
    results = [_result("a", "src/a.py", 0.9), _result("b", "src/b.py", 0.8)]
    strategy = LlmRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeGenerationProvider("not-json"),
        candidate_limit=2,
    )

    reranked = strategy.search("query", 2)

    assert reranked == results


def test_llm_rerank_response_parser_ignores_invalid_and_duplicate_indices() -> None:
    indices = LlmRerankResponseParser().parse_indices(
        '{"results":[{"index":2},{"index":2},{"index":99},{"index":"1"},{"index":"x"}]}',
        candidate_count=3,
    )

    assert indices == [2, 1]


def _result(item_id: str, path: str, score: float) -> SearchResult:
    return SearchResult(
        item=CodeItem(
            id=item_id,
            path=path,
            title=path,
            content=f"{path} handles auth commands",
            start_line=1,
            end_line=3,
        ),
        score=score,
    )
