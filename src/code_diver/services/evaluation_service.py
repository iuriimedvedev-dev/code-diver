from __future__ import annotations

from typing import Any

from ..domain import CodeItem, EvalCase, EvalResult
from ..providers import EmbeddingProvider
from .retrieval_service import RetrievalService


class EvaluationService:
    def __init__(self, retrieval_service: RetrievalService | None = None):
        self.retrieval_service = retrieval_service or RetrievalService()

    def evaluate(
        self,
        cases: list[EvalCase],
        provider: EmbeddingProvider,
        items: list[CodeItem],
        vectors: list[list[float]],
        limit: int,
    ) -> tuple[dict[str, Any], list[EvalResult]]:
        results: list[EvalResult] = []
        for case in cases:
            search_results = self.retrieval_service.search(provider, case.query, items, vectors, limit)
            retrieved = [result.item.id for result in search_results]
            matched_ranks = [
                rank
                for rank, result in enumerate(search_results, start=1)
                if self._matches_any_expected(result.item, case.expected)
            ]
            hit = bool(matched_ranks)
            reciprocal_rank = 1.0 / matched_ranks[0] if matched_ranks else 0.0
            match_count = len(matched_ranks)
            precision = match_count / max(len(search_results), 1)
            recall = min(match_count / max(len(case.expected), 1), 1.0)
            results.append(
                EvalResult(
                    case_id=case.id,
                    query=case.query,
                    expected=case.expected,
                    retrieved=retrieved,
                    hit=hit,
                    reciprocal_rank=reciprocal_rank,
                    precision=precision,
                    recall=recall,
                )
            )

        metrics = {
            "cases": len(results),
            f"hit_rate@{limit}": self._mean(1.0 if result.hit else 0.0 for result in results),
            f"mrr@{limit}": self._mean(result.reciprocal_rank for result in results),
            f"precision@{limit}": self._mean(result.precision for result in results),
            f"recall@{limit}": self._mean(result.recall for result in results),
        }
        return metrics, results

    def _matches_any_expected(self, item: CodeItem, expected: list[str]) -> bool:
        return any(self._matches_expected(item, value) for value in expected)

    def _matches_expected(self, item: CodeItem, expected: str) -> bool:
        normalized = expected.strip()
        return (
            item.id == normalized
            or item.path == normalized
            or item.path.startswith(normalized.rstrip("/") + "/")
            or item.id.startswith(normalized + "#")
        )

    def _mean(self, values: Any) -> float:
        materialized = list(values)
        if not materialized:
            return 0.0
        return sum(materialized) / len(materialized)
