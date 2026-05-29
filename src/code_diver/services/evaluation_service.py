from __future__ import annotations

from time import perf_counter
from typing import Any

from ..domain import EvalCase, EvalResult
from ..strategies import RetrievalStrategy


class EvaluationService:
    def __init__(self, retrieval_strategy: RetrievalStrategy):
        self.retrieval_strategy = retrieval_strategy

    def evaluate(
        self,
        cases: list[EvalCase],
        limit: int,
    ) -> tuple[dict[str, Any], list[EvalResult]]:
        results: list[EvalResult] = []
        durations_ms: list[float] = []
        for case in cases:
            started = perf_counter()
            search_results = self.retrieval_strategy.search(case.query, limit)
            durations_ms.append((perf_counter() - started) * 1000)
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
            "search_duration_ms_total": sum(durations_ms),
            "search_duration_ms_mean": self._mean(durations_ms),
            "search_duration_ms_p95": self._percentile(durations_ms, 0.95),
        }
        return metrics, results

    def _matches_any_expected(self, item: object, expected: list[str]) -> bool:
        return any(self._matches_expected(item, value) for value in expected)

    def _matches_expected(self, item: object, expected: str) -> bool:
        normalized = expected.strip()
        return (
            getattr(item, "id") == normalized
            or getattr(item, "path") == normalized
            or getattr(item, "path").startswith(normalized.rstrip("/") + "/")
            or getattr(item, "id").startswith(normalized + "#")
        )

    def _mean(self, values: Any) -> float:
        materialized = list(values)
        if not materialized:
            return 0.0
        return sum(materialized) / len(materialized)

    def _percentile(self, values: list[float], quantile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(int(round((len(ordered) - 1) * quantile)), len(ordered) - 1)
        return ordered[index]
