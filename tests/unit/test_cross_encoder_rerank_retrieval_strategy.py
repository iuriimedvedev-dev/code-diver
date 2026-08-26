from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from code_diver.config.trace_config import TraceConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.reranking import RerankScore
from code_diver.strategies.cross_encoder_rerank_retrieval_strategy import (
    CrossEncoderRerankRetrievalStrategy,
)
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


def test_cross_encoder_rerank_reorders_candidates_and_logs_documents(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    provider = FakeRerankProvider(
        [RerankScore(index=2, score=0.99), RerankScore(index=0, score=0.5)]
    )
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(
            [
                _result("a", "src/a.py", 0.9),
                _result("b", "src/b.py", 0.8),
                _result("c", "src/c.py", 0.7),
            ]
        ),
        provider,
        CrossEncoderRerankConfig(candidate_limit=3, max_document_chars=40),
        trace_logger=TraceLogger(
            TraceConfig(enabled=True, artifact=trace_path, include_prompts=True)
        ),
    )

    reranked = strategy.search("where is auth handled", 2)

    assert [result.item.path for result in reranked] == ["src/c.py", "src/a.py"]
    assert provider.calls[0][2] == 2
    assert "path: src/a.py" in provider.calls[0][1][0]
    records = [
        json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == [
        "cross_encoder_rerank_request",
        "cross_encoder_rerank_response",
    ]
    assert "documents" in records[0]["payload"]
    assert records[1]["payload"]["scores"][0] == {"index": 2, "score": 0.99}


def test_cross_encoder_rerank_falls_back_to_base_order_on_error() -> None:
    class FailingProvider(FakeRerankProvider):
        def rerank(
            self, query: str, documents: list[str], top_n: int
        ) -> list[RerankScore]:
            raise RuntimeError("rerank down")

    results = [_result("a", "src/a.py", 0.9), _result("b", "src/b.py", 0.8)]
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        FailingProvider([]),
        CrossEncoderRerankConfig(candidate_limit=2),
    )

    assert strategy.search("query", 2) == results


def test_cross_encoder_rerank_limits_documents_without_discarding_tail() -> None:
    results = [
        _result("a", "src/a.py", 0.9),
        _result("b", "src/b.py", 0.8),
        _result("c", "src/c.py", 0.7),
        _result("d", "src/d.py", 0.6),
    ]
    provider = FakeRerankProvider([RerankScore(index=1, score=0.99)])
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        CrossEncoderRerankConfig(candidate_limit=2),
    )

    reranked = strategy.search("query", 4)

    assert len(provider.calls[0][1]) == 2
    assert provider.calls[0][2] == 2
    assert [result.item.path for result in reranked] == [
        "src/b.py",
        "src/a.py",
        "src/c.py",
        "src/d.py",
    ]


def test_cross_encoder_rerank_preserves_confident_top_candidate() -> None:
    results = [
        _result("a", "src/a.py", 0.95),
        _result("b", "src/b.py", 0.80),
        _result("c", "src/c.py", 0.70),
    ]
    provider = FakeRerankProvider(
        [RerankScore(index=1, score=0.99), RerankScore(index=0, score=0.2)]
    )
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        CrossEncoderRerankConfig(
            candidate_limit=3,
            preserve_top_candidate=True,
            preserve_top_score_margin=0.1,
        ),
    )

    reranked = strategy.search("query", 3)

    assert [result.item.path for result in reranked] == [
        "src/a.py",
        "src/b.py",
        "src/c.py",
    ]


def test_cross_encoder_rerank_skips_provider_for_confident_base_top(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    results = [
        _result("a", "src/a.py", 0.95),
        _result("b", "src/b.py", 0.80),
        _result("c", "src/c.py", 0.70),
    ]
    provider = FakeRerankProvider([RerankScore(index=1, score=0.99)])
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        CrossEncoderRerankConfig(
            candidate_limit=3,
            skip_when_top_margin_at_least=0.1,
        ),
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path)),
    )

    reranked = strategy.search("query", 3)

    assert [result.item.path for result in reranked] == [
        "src/a.py",
        "src/b.py",
        "src/c.py",
    ]
    assert provider.calls == []
    records = [
        json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["event"] == "cross_encoder_rerank_skipped"
    assert records[0]["payload"]["reason"] == "confident_base_top"
    assert records[0]["payload"]["margin"] == pytest.approx(0.15)


def test_cross_encoder_rerank_widens_window_when_base_ranking_is_flat(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    # Ranks 1..6 are within widen_score_margin_below of each other -- a "flat" base ranking --
    # and the correct file sits at rank 6, past the normal candidate_limit of 3.
    results = [
        _result("a", "src/a.py", 0.90),
        _result("b", "src/b.py", 0.89),
        _result("c", "src/c.py", 0.88),
        _result("d", "src/d.py", 0.87),
        _result("e", "src/e.py", 0.86),
        _result("target", "src/target.py", 0.85),
    ]
    provider = FakeRerankProvider([RerankScore(index=5, score=0.99)])
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        CrossEncoderRerankConfig(
            candidate_limit=3,
            widen_when_uncertain_enabled=True,
            widen_candidate_limit=6,
            widen_margin_check_rank=6,
            widen_score_margin_below=0.1,
        ),
        trace_logger=TraceLogger(TraceConfig(enabled=True, artifact=trace_path)),
    )

    reranked = strategy.search("where is x coordinated", 6)

    assert len(provider.calls[0][1]) == 6
    assert reranked[0].item.path == "src/target.py"
    records = [
        json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    widen_records = [record for record in records if record["event"] == "cross_encoder_rerank_widened"]
    assert len(widen_records) == 1
    assert widen_records[0]["payload"]["widened_candidate_limit"] == 6


def test_cross_encoder_rerank_keeps_base_limit_when_ranking_is_confident() -> None:
    results = [
        _result("a", "src/a.py", 0.95),
        _result("b", "src/b.py", 0.60),
        _result("c", "src/c.py", 0.55),
        _result("d", "src/d.py", 0.50),
        _result("e", "src/e.py", 0.45),
        _result("target", "src/target.py", 0.40),
    ]
    provider = FakeRerankProvider([RerankScore(index=0, score=0.99)])
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        CrossEncoderRerankConfig(
            candidate_limit=3,
            widen_when_uncertain_enabled=True,
            widen_candidate_limit=6,
            widen_margin_check_rank=6,
            widen_score_margin_below=0.1,
        ),
    )

    strategy.search("mechanical exact-name query", 6)

    assert len(provider.calls[0][1]) == 3


def test_cross_encoder_rerank_widen_gate_disabled_by_default_reproduces_base_limit() -> None:
    results = [
        _result("a", "src/a.py", 0.90),
        _result("b", "src/b.py", 0.89),
        _result("target", "src/target.py", 0.85),
    ]
    provider = FakeRerankProvider([RerankScore(index=0, score=0.99)])
    strategy = CrossEncoderRerankRetrievalStrategy(
        FakeStrategy(results),
        provider,
        CrossEncoderRerankConfig(candidate_limit=2),
    )

    strategy.search("query", 3)

    assert len(provider.calls[0][1]) == 2


def _result(item_id: str, path: str, score: float) -> SearchResult:
    return SearchResult(
        item=CodeItem(
            id=item_id, path=path, title=path, content=f"{path} handles auth commands"
        ),
        score=score,
    )
