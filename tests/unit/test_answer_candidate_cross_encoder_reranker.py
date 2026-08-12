from __future__ import annotations

import pytest

from code_diver.answering import AnswerCandidateCrossEncoderReranker
from code_diver.config.cross_encoder_rerank_config import CrossEncoderRerankConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.reranking import RerankScore

pytestmark = pytest.mark.unit


class FakeRerankProvider:
    name = "fake_rerank"
    model = "fake-cross-encoder"

    def __init__(self, scores: list[RerankScore] | None = None, error: Exception | None = None):
        self.scores = scores or []
        self.error = error
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankScore]:
        self.calls.append((query, documents, top_n))
        if self.error is not None:
            raise self.error
        return self.scores


def _result(path: str, score: float) -> SearchResult:
    return SearchResult(
        item=CodeItem(id=path, path=path, title=path, content=f"{path} body text"),
        score=score,
    )


def _candidates(count: int) -> list[SearchResult]:
    return [_result(f"src/f{index}.py", 1.0 - index / 100) for index in range(count)]


def _config(**overrides) -> CrossEncoderRerankConfig:
    return CrossEncoderRerankConfig(**{"candidate_limit": 34, "max_document_chars": 850, **overrides})


def test_it_orders_by_cross_encoder_score_and_keeps_unscored_candidates_behind() -> None:
    candidates = _candidates(5)
    provider = FakeRerankProvider([RerankScore(index=3, score=0.9), RerankScore(index=1, score=0.4)])

    ranked, payload = AnswerCandidateCrossEncoderReranker(provider, _config()).rerank(
        "how does auth work?", candidates, 4
    )

    assert [result.item.path for result in ranked] == [
        "src/f3.py",
        "src/f1.py",
        "src/f0.py",
        "src/f2.py",
    ]
    assert payload["selected_indices"] == [4, 2]
    assert payload["candidate_count"] == 5


def test_the_payload_keeps_the_generative_reranker_key_names() -> None:
    provider = FakeRerankProvider([RerankScore(index=0, score=0.7)])

    _, payload = AnswerCandidateCrossEncoderReranker(provider, _config()).rerank(
        "q", _candidates(3), 2
    )

    assert payload["enabled"] is True
    assert payload["model"] == "fake-cross-encoder"
    assert payload["selected_candidates"][0]["path"] == "src/f0.py"
    assert payload["selected_candidates"][0]["confidence"] == pytest.approx(0.7)
    # A cross-encoder emits no tokens; reporting anything else would corrupt cost-per-case.
    assert payload["total_tokens"] == 0
    assert payload["estimated_cost"] == 0.0


def test_out_of_range_and_repeated_indices_cannot_drop_or_duplicate_a_candidate() -> None:
    candidates = _candidates(3)
    provider = FakeRerankProvider(
        [
            RerankScore(index=99, score=0.9),
            RerankScore(index=2, score=0.8),
            RerankScore(index=2, score=0.7),
            RerankScore(index=-1, score=0.6),
        ]
    )

    ranked, _ = AnswerCandidateCrossEncoderReranker(provider, _config()).rerank("q", candidates, 3)

    assert [result.item.path for result in ranked] == ["src/f2.py", "src/f0.py", "src/f1.py"]


def test_a_provider_failure_falls_back_to_base_order_instead_of_raising() -> None:
    provider = FakeRerankProvider(error=RuntimeError("connection refused"))

    ranked, payload = AnswerCandidateCrossEncoderReranker(provider, _config()).rerank(
        "q", _candidates(3), 2
    )

    assert [result.item.path for result in ranked] == ["src/f0.py", "src/f1.py"]
    assert payload["fallback"] == "base_candidate_order"
    assert payload["error"] == "connection refused"


def test_it_only_sends_candidate_limit_documents() -> None:
    provider = FakeRerankProvider([RerankScore(index=0, score=0.5)])

    AnswerCandidateCrossEncoderReranker(provider, _config(candidate_limit=4)).rerank(
        "q", _candidates(10), 10
    )

    _query, documents, top_n = provider.calls[0]
    assert len(documents) == 4
    assert top_n == 4
    assert documents[0].startswith("path: src/f0.py")


def test_document_text_is_truncated_to_the_configured_budget() -> None:
    provider = FakeRerankProvider([RerankScore(index=0, score=0.5)])
    long = SearchResult(
        item=CodeItem(id="a", path="a.py", title="a.py", content="x" * 5000), score=1.0
    )

    AnswerCandidateCrossEncoderReranker(provider, _config(max_document_chars=100)).rerank(
        "q", [long, _result("b.py", 0.5)], 2
    )

    _, documents, _ = provider.calls[0]
    assert documents[0].count("x") == 100
