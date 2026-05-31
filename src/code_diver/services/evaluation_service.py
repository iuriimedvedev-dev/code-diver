from __future__ import annotations

import math
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
            file_metrics = self._file_metrics(search_results, case.expected, limit)
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
                    retrieved_files=file_metrics["retrieved_files"],
                    file_hit=bool(file_metrics["file_hit"]),
                    file_reciprocal_rank=float(file_metrics["file_mrr"]),
                    file_precision_at_r=float(file_metrics["file_precision_at_r"]),
                    file_recall=float(file_metrics["file_recall"]),
                    ndcg=float(file_metrics["ndcg"]),
                    average_precision=float(file_metrics["average_precision"]),
                )
            )

        metrics = {
            "cases": len(results),
            f"hit_rate@{limit}": self._mean(1.0 if result.hit else 0.0 for result in results),
            f"mrr@{limit}": self._mean(result.reciprocal_rank for result in results),
            f"precision@{limit}": self._mean(result.precision for result in results),
            f"recall@{limit}": self._mean(result.recall for result in results),
            "hit_rate@1": self._mean(1.0 if self._hit_at(result, 1) else 0.0 for result in results),
            "hit_rate@3": self._mean(1.0 if self._hit_at(result, 3) else 0.0 for result in results),
            f"file_hit_rate@{limit}": self._mean(1.0 if result.file_hit else 0.0 for result in results),
            f"file_mrr@{limit}": self._mean(result.file_reciprocal_rank for result in results),
            "file_precision@R": self._mean(result.file_precision_at_r for result in results),
            f"file_recall@{limit}": self._mean(result.file_recall for result in results),
            f"ndcg@{limit}": self._mean(result.ndcg for result in results),
            f"map@{limit}": self._mean(result.average_precision for result in results),
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

    def _file_metrics(self, search_results: list[Any], expected: list[str], limit: int) -> dict[str, Any]:
        files = self._dedupe_files(getattr(result.item, "path") for result in search_results[:limit])
        matched_ranks = [
            rank
            for rank, path in enumerate(files, start=1)
            if self._matches_any_path_expected(path, expected)
        ]
        expected_count = max(len(expected), 1)
        matched_expected_count = sum(1 for value in expected if any(self._matches_path_expected(path, value) for path in files))
        r = min(expected_count, limit)
        top_r = files[:r]
        file_precision_at_r = (
            sum(1 for path in top_r if self._matches_any_path_expected(path, expected)) / max(r, 1)
        )
        return {
            "retrieved_files": files,
            "file_hit": bool(matched_ranks),
            "file_mrr": 1.0 / matched_ranks[0] if matched_ranks else 0.0,
            "file_precision_at_r": file_precision_at_r,
            "file_recall": min(matched_expected_count / expected_count, 1.0),
            "ndcg": self._ndcg(files, expected, limit),
            "average_precision": self._average_precision(files, expected),
        }

    def _dedupe_files(self, paths: Any) -> list[str]:
        seen: set[str] = set()
        files: list[str] = []
        for path in paths:
            text = str(path)
            if text in seen:
                continue
            seen.add(text)
            files.append(text)
        return files

    def _matches_any_path_expected(self, path: str, expected: list[str]) -> bool:
        return any(self._matches_path_expected(path, value) for value in expected)

    def _matches_path_expected(self, path: str, expected: str) -> bool:
        normalized = expected.strip()
        return path == normalized or path.startswith(normalized.rstrip("/") + "/")

    def _ndcg(self, files: list[str], expected: list[str], limit: int) -> float:
        dcg = 0.0
        matched_expected: set[int] = set()
        for rank, path in enumerate(files[:limit], start=1):
            match_index = self._first_unmatched_expected(path, expected, matched_expected)
            if match_index is not None:
                matched_expected.add(match_index)
                dcg += 1.0 / math.log2(rank + 1)
        ideal_relevant = min(len(expected), limit)
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
        return dcg / ideal if ideal else 0.0

    def _average_precision(self, files: list[str], expected: list[str]) -> float:
        hits = 0
        total = 0.0
        matched_expected: set[int] = set()
        for rank, path in enumerate(files, start=1):
            match_index = self._first_unmatched_expected(path, expected, matched_expected)
            if match_index is None:
                continue
            matched_expected.add(match_index)
            hits += 1
            total += hits / rank
        return total / max(len(expected), 1)

    def _first_unmatched_expected(self, path: str, expected: list[str], matched: set[int]) -> int | None:
        for index, value in enumerate(expected):
            if index in matched:
                continue
            if self._matches_path_expected(path, value):
                return index
        return None

    def _hit_at(self, result: EvalResult, limit: int) -> bool:
        return any(self._matches_path_or_id(value, result.expected) for value in result.retrieved[:limit])

    def _matches_path_or_id(self, value: str, expected: list[str]) -> bool:
        return any(value == item or value.startswith(item + "#") or value.startswith(item.rstrip("/") + "/") for item in expected)

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
