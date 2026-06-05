from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config.trace_config import TraceConfig
from code_diver.config.llm_rerank_config import LlmRerankConfig
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


class FlakyGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def generate_json_result(self, prompt: str) -> GenerationResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient 499 cancelled")
        return GenerationResult(
            text='{"results":[{"index":2}]}',
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
        LlmRerankConfig(candidate_limit=3),
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
        LlmRerankConfig(candidate_limit=2),
    )

    reranked = strategy.search("query", 2)

    assert reranked == results


def test_llm_rerank_retries_transient_generation_error(tmp_path: Path) -> None:
    results = [_result("a", "src/a.py", 0.9), _result("b", "src/b.py", 0.8)]
    provider = FlakyGenerationProvider()
    trace_path = tmp_path / "trace.jsonl"
    strategy = LlmRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        LlmRerankConfig(candidate_limit=2, retry_attempts=2, retry_base_delay_seconds=0),
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=False)),
    )

    reranked = strategy.search("query", 2)

    assert [result.item.path for result in reranked] == ["src/b.py", "src/a.py"]
    assert provider.calls == 2
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == [
        "llm_rerank_prompt",
        "llm_rerank_error",
        "llm_rerank_response",
    ]
    assert records[1]["payload"]["attempt"] == 1
    assert records[1]["payload"]["will_retry"] is True
    assert records[2]["payload"]["attempt"] == 2


def test_llm_rerank_response_parser_ignores_invalid_and_duplicate_indices() -> None:
    indices = LlmRerankResponseParser().parse_indices(
        '{"results":[{"index":2},{"index":2},{"index":99},{"index":"1"},{"index":"x"}]}',
        candidate_count=3,
    )

    assert indices == [2, 1]


def test_llm_rerank_response_parser_accepts_loose_index_lists() -> None:
    parser = LlmRerankResponseParser()

    assert parser.parse_indices("[3, 1, 3, 99]", candidate_count=5) == [3, 1]
    assert parser.parse_indices("index: 4\nindex: 2", candidate_count=5) == [4, 2]
    assert parser.parse_indices("candidate 5, candidate 1", candidate_count=5) == [5, 1]


def test_llm_rerank_response_parser_rejects_unstructured_numbers() -> None:
    response = "The answer is around line 42 in src/auth.py, not candidate text."

    assert LlmRerankResponseParser().parse_indices(response, candidate_count=50) == []


def test_llm_rerank_can_preserve_confident_base_top() -> None:
    results = [
        _result("a", "src/a.py", 0.9),
        _result("b", "src/b.py", 0.1),
    ]
    strategy = LlmRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeGenerationProvider('{"results":[{"index":2,"confidence":0.9}]}'),
        LlmRerankConfig(candidate_limit=2, preserve_top_candidate=True, preserve_top_score_margin=0.5),
    )

    reranked = strategy.search("query", 2)

    assert [result.item.path for result in reranked] == ["src/a.py", "src/b.py"]


def test_llm_rerank_limits_llm_prefix_and_preserves_base_tail() -> None:
    results = [
        _result("a", "src/a.py", 0.9),
        _result("b", "src/b.py", 0.8),
        _result("c", "src/c.py", 0.7),
        _result("d", "src/d.py", 0.6),
    ]
    strategy = LlmRerankRetrievalStrategy(
        FakeStrategy(results),
        FakeGenerationProvider('{"results":[{"index":3},{"index":4},{"index":2}]}'),
        LlmRerankConfig(candidate_limit=4, rerank_limit=1),
    )

    reranked = strategy.search("query", 3)

    assert [result.item.path for result in reranked] == ["src/c.py", "src/a.py", "src/b.py"]
    assert '"limit": 1' in strategy.generation_provider.prompts[0]


def test_llm_rerank_prompt_marks_path_roles_and_prefers_implementation_owners() -> None:
    results = [
        _result("test", "src/tests/test_auth.py", 0.9),
        _result("impl", "src/auth.py", 0.8),
        _result("doc", "README.md", 0.7),
    ]
    provider = FakeGenerationProvider('{"results":[{"index":2}]}')
    strategy = LlmRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        LlmRerankConfig(candidate_limit=3),
    )

    strategy.search("where is auth implemented?", 2)

    prompt = provider.prompts[0]
    assert '"path_role": "test"' in prompt
    assert '"path_role": "implementation"' in prompt
    assert '"path_role": "doc"' in prompt
    assert "Prefer implementation owner files over tests" in prompt


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
