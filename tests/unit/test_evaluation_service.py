from __future__ import annotations

import pytest

from code_diver.domain import CodeItem, EvalCase, SearchResult
from code_diver.services.evaluation_service import EvaluationService
from code_diver.strategies import RetrievalStrategy


pytestmark = pytest.mark.unit


class StaticStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                CodeItem(id="wrong#1", path="wrong.py", title="Wrong", content="", metadata={"index_kind": "chunk"}),
                0.9,
            ),
            SearchResult(
                CodeItem(
                    id="target.py#1",
                    path="target.py",
                    title="Target",
                    content="",
                    metadata={"index_kind": "file_summary"},
                ),
                0.8,
            ),
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
    assert metrics["hit_rate@1"] == 0.0
    assert metrics["hit_rate@3"] == 1.0
    assert metrics["file_hit_rate@2"] == 1.0
    assert metrics["file_mrr@2"] == 0.5
    assert metrics["file_precision@R"] == 0.0
    assert metrics["file_recall@2"] == 1.0
    assert metrics["ndcg@2"] == pytest.approx(0.6309297536)
    assert metrics["map@2"] == 0.5
    assert metrics["bucket.semantic.cases"] == 1
    assert metrics["bucket.semantic.file_hit_rate@2"] == 1.0
    assert metrics["top_result_kind.chunk.rate"] == 1.0
    assert metrics["first_relevant_kind.file_summary.rate"] == 1.0
    assert results[0].retrieved_files == ["wrong.py", "target.py"]
    assert results[0].bucket == "semantic"
    assert results[0].top_result_kind == "chunk"
    assert results[0].first_relevant_kind == "file_summary"
    assert results[0].file_reciprocal_rank == 0.5


class DuplicateFileStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(CodeItem(id="target.py#1", path="target.py", title="Target 1", content=""), 0.9),
            SearchResult(CodeItem(id="target.py#2", path="target.py", title="Target 2", content=""), 0.8),
            SearchResult(CodeItem(id="other.py#1", path="other.py", title="Other", content=""), 0.7),
        ][:limit]


def test_evaluation_service_file_metrics_dedupe_retrieved_files() -> None:
    metrics, results = EvaluationService(DuplicateFileStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=3,
    )

    assert metrics["precision@3"] == pytest.approx(2 / 3)
    assert metrics["file_precision@R"] == 1.0
    assert metrics["file_recall@3"] == 1.0
    assert metrics["ndcg@3"] == 1.0
    assert metrics["map@3"] == 1.0
    assert results[0].retrieved_files == ["target.py", "other.py"]


class SymbolIdStrategy(RetrievalStrategy):
    def search(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(
                CodeItem(id="target.py::TargetClass#abc", path="target.py", title="TargetClass", content=""),
                0.9,
            ),
        ][:limit]


def test_evaluation_service_hit_at_matches_symbol_ids_for_expected_file_paths() -> None:
    metrics, _ = EvaluationService(SymbolIdStrategy()).evaluate(
        [EvalCase(id="case", query="find target", expected=["target.py"])],
        limit=1,
    )

    assert metrics["hit_rate@1"] == 1.0
