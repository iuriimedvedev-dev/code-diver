from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.reranking import RerankScore
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import CrossEncoderRerankRetrievalStrategy
from code_diver.tracing import TraceLogger


pytestmark = pytest.mark.unit


class FakeStrategy:
    def __init__(self, results: list[SearchResult]):
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        return self.results[:limit]


class FakeRerankProvider:
    name = "fake_rerank"
    model = "fake-cross-encoder"

    def __init__(self, scores: list[RerankScore]):
        self.scores = scores
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankScore]:
        self.calls.append((query, documents, top_n))
        return self.scores


def test_cross_encoder_rerank_reorders_candidates_and_logs_documents(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    provider = FakeRerankProvider([RerankScore(index=2, score=0.99), RerankScore(index=0, score=0.5)])
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy([_result("a", "src/a.py", 0.9), _result("b", "src/b.py", 0.8), _result("c", "src/c.py", 0.7)]),
        provider,
        CrossEncoderRerankConfig(candidate_limit=3, max_document_chars=40),
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path, include_prompts=True)),
    )

    reranked = strategy.search("where is auth handled", 2)

    assert [result.item.path for result in reranked] == ["src/c.py", "src/a.py"]
    assert provider.calls[0][2] == 2
    assert "path: src/a.py" in provider.calls[0][1][0]
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == [
        "cross_encoder_rerank_request",
        "cross_encoder_rerank_response",
    ]
    assert "documents" in records[0]["payload"]
    assert records[1]["payload"]["scores"][0] == {"index": 2, "score": 0.99}


def test_cross_encoder_rerank_falls_back_to_base_order_on_error() -> None:
    class FailingProvider(FakeRerankProvider):
        def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankScore]:
            raise RuntimeError("rerank down")

    results = [_result("a", "src/a.py", 0.9), _result("b", "src/b.py", 0.8)]
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FailingProvider([]),
        CrossEncoderRerankConfig(candidate_limit=2),
    )

    assert strategy.search("query", 2) == results


def _result(item_id: str, path: str, score: float) -> SearchResult:
    return SearchResult(
        item=CodeItem(id=item_id, path=path, title=path, content=f"{path} handles auth commands"),
        score=score,
    )
