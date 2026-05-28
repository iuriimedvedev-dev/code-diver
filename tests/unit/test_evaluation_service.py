from __future__ import annotations

import pytest

from code_diver.domain import CodeItem, EvalCase, SearchResult
from code_diver.services.evaluation_service import EvaluationService
from code_diver.strategies import RetrievalStrategy


pytestmark = pytest.mark.unit


class StaticStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(CodeItem(id="wrong#1", path="wrong.py", title="Wrong", content=""), 0.9),
            SearchResult(CodeItem(id="target.py#1", path="target.py", title="Target", content=""), 0.8),
        ][:limit]


def test_evaluation_service_computes_ranked_metrics() -> None:
    metrics, results = EvaluationService(StaticStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=2,
    )

    assert results[0].hit is True
    assert results[0].reciprocal_rank == 0.5
    assert results[0].precision == 0.5
    assert results[0].recall == 1.0
    assert metrics["hit_rate@2"] == 1.0
    assert metrics["mrr@2"] == 0.5
