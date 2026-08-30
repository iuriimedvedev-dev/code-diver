from __future__ import annotations

import fnmatch
import math
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Any

from ..domain import CodeItemIndexKindResolver, EvalCase, EvalResult
from ..strategies import RetrievalStrategy
from ..tracing import TraceLogger
from .eval_case_bucket_classifier import EvalCaseBucketClassifier
from .evaluation_statistics import EvaluationStatistics


class EvaluationService:
    def __init__(
        self,
        retrieval_strategy: RetrievalStrategy,
        trace_logger: TraceLogger | None = None,
        progress_interval: int = 50,
    ):
        self.retrieval_strategy = retrieval_strategy
        self.bucket_classifier = EvalCaseBucketClassifier()
        self.index_kind_resolver = CodeItemIndexKindResolver()
        self.statistics = EvaluationStatistics()
        self.trace_logger = trace_logger or TraceLogger.disabled()
        self.progress_interval = max(int(progress_interval or 1), 1)

    def evaluate(
        self,
        cases: list[EvalCase],
        limit: int,
        workers: int = 1,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[dict[str, Any], list[EvalResult]]:
        worker_count = max(int(workers or 1), 1)
        started = perf_counter()
        self.trace_logger.write(
            "evaluation_started",
            {
                "cases": len(cases),
                "limit": limit,
                "workers": worker_count,
                "progress_interval": self.progress_interval,
            },
        )
        failures: list[dict[str, Any]] = []
        if worker_count == 1 or len(cases) <= 1:
            rows = []
            for index, case in enumerate(cases, start=1):
                row, failure = self._evaluate_case_or_failure(case, limit)
                rows.append(row)
                if failure is not None:
                    failures.append(failure)
                self._trace_progress(index, len(cases), started)
                if progress_callback is not None:
                    progress_callback(index, len(cases))
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(self._evaluate_case_or_failure, case, limit): (index, case)
                    for index, case in enumerate(cases)
                }
                rows_by_index: list[tuple[EvalResult, float] | None] = [None] * len(cases)
                for completed, future in enumerate(as_completed(futures), start=1):
                    index, case = futures[future]
                    try:
                        row, failure = future.result()
                    except Exception as exc:
                        failure = self._failure_payload(case, exc)
                        rows_by_index[index] = self._failed_case(case)
                        self.trace_logger.write("evaluation_case_failed", failure)
                    else:
                        rows_by_index[index] = row
                    if failure is not None:
                        failures.append(failure)
                    self._trace_progress(completed, len(cases), started)
                    if progress_callback is not None:
                        progress_callback(completed, len(cases))
                rows = [row for row in rows_by_index if row is not None]
        results = [result for result, _ in rows]
        durations_ms = [duration_ms for _, duration_ms in rows]
        failed_case_ids = {failure["case_id"] for failure in failures}
        successful_durations_ms = [
            duration_ms for result, duration_ms in rows if result.case_id not in failed_case_ids
        ]
        failed_durations_ms = [
            duration_ms for result, duration_ms in rows if result.case_id in failed_case_ids
        ]

        metrics = {
            "cases": len(results),
            "evaluation_workers": worker_count,
            f"hit_rate@{limit}": self._mean(1.0 if result.hit else 0.0 for result in results),
            f"mrr@{limit}": self._mean(result.reciprocal_rank for result in results),
            f"precision@{limit}": self._mean(result.precision for result in results),
            f"recall@{limit}": self._mean(result.recall for result in results),
            "hit_rate@1": self._mean(1.0 if self._hit_at(result, 1) else 0.0 for result in results),
            "hit_rate@3": self._mean(1.0 if self._hit_at(result, 3) else 0.0 for result in results),
            "hit_rate@5": self._mean(1.0 if self._hit_at(result, 5) else 0.0 for result in results),
            "file_hit_rate@1": self._mean(1.0 if self._file_hit_at(result, 1) else 0.0 for result in results),
            "file_hit_rate@3": self._mean(1.0 if self._file_hit_at(result, 3) else 0.0 for result in results),
            "file_hit_rate@5": self._mean(1.0 if self._file_hit_at(result, 5) else 0.0 for result in results),
            f"file_hit_rate@{limit}": self._mean(1.0 if result.file_hit else 0.0 for result in results),
            f"file_mrr@{limit}": self._mean(result.file_reciprocal_rank for result in results),
            "file_precision@R": self._mean(result.file_precision_at_r for result in results),
            f"file_recall@{limit}": self._mean(result.file_recall for result in results),
            f"ndcg@{limit}": self._mean(result.ndcg for result in results),
            f"map@{limit}": self._mean(result.average_precision for result in results),
            "search_duration_ms_total": sum(durations_ms),
            "search_duration_ms_mean": self._mean(durations_ms),
            "search_duration_ms_p95": self._percentile(durations_ms, 0.95),
            "search_success_cases": len(successful_durations_ms),
            "search_success_duration_ms_total": sum(successful_durations_ms),
            "search_success_duration_ms_mean": self._mean(successful_durations_ms),
            "search_success_duration_ms_p95": self._percentile(successful_durations_ms, 0.95),
            "search_failed_cases": len(failed_durations_ms),
            "search_failed_duration_ms_total": sum(failed_durations_ms),
            "search_failed_duration_ms_mean": self._mean(failed_durations_ms),
            "search_failed_duration_ms_p95": self._percentile(failed_durations_ms, 0.95),
            "degraded": bool(failures),
            "degraded_cases": len(failures),
            "degraded_case_rate": len(failures) / max(len(cases), 1),
            "failure_details": failures[:20],
        }
        metrics.update(self._derived_metrics(results, limit, metrics))
        metrics.update(self._statistical_metrics(results, durations_ms, limit))
        metrics.update(self._bucket_metrics(results, limit))
        metrics.update(self._item_kind_metrics(results))
        self.trace_logger.write(
            "evaluation_completed",
            {
                "cases": len(results),
                "limit": limit,
                "workers": worker_count,
                "duration_ms": (perf_counter() - started) * 1000,
                "hit_rate@1": metrics.get("hit_rate@1"),
                f"hit_rate@{limit}": metrics.get(f"hit_rate@{limit}"),
                f"ndcg@{limit}": metrics.get(f"ndcg@{limit}"),
                f"file_recall@{limit}": metrics.get(f"file_recall@{limit}"),
                "degraded": bool(failures),
                "degraded_cases": len(failures),
                "failures": failures[:20],
            },
        )
        return metrics, results

    def _evaluate_case_or_failure(self, case: EvalCase, limit: int) -> tuple[tuple[EvalResult, float], dict[str, Any] | None]:
        started = perf_counter()
        try:
            return self._evaluate_case(case, limit), None
        except Exception as exc:
            failure = self._failure_payload(case, exc)
            self.trace_logger.write("evaluation_case_failed", failure)
            return self._failed_case(case, (perf_counter() - started) * 1000), failure

    def _failed_case(self, case: EvalCase, duration_ms: float = 0.0) -> tuple[EvalResult, float]:
        return (
            EvalResult(
                case_id=case.id,
                query=case.query,
                expected=case.expected,
                retrieved=[],
                hit=False,
                reciprocal_rank=0.0,
                precision=0.0,
                recall=0.0,
                retrieved_files=[],
                bucket=self.bucket_classifier.classify(case.query),
                top_result_kind="none",
                first_relevant_kind="none",
                file_hit=False,
                file_reciprocal_rank=0.0,
                file_precision_at_r=0.0,
                file_recall=0.0,
                ndcg=0.0,
                average_precision=0.0,
            ),
            duration_ms,
        )

    def _failure_payload(self, case: EvalCase, exc: Exception) -> dict[str, Any]:
        return {
            "case_id": case.id,
            "query": case.query,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    def _trace_progress(self, completed: int, total: int, started: float) -> None:
        if completed < total and completed % self.progress_interval != 0:
            return
        elapsed_ms = (perf_counter() - started) * 1000
        self.trace_logger.write(
            "evaluation_progress",
            {
                "completed": completed,
                "total": total,
                "progress": completed / max(total, 1),
                "elapsed_ms": elapsed_ms,
                "cases_per_second": completed / max(elapsed_ms / 1000, 0.001),
            },
        )

    def _evaluate_case(self, case: EvalCase, limit: int) -> tuple[EvalResult, float]:
        started = perf_counter()
        search_results = self.retrieval_strategy.search(case.query, limit)
        duration_ms = (perf_counter() - started) * 1000
        retrieved = [result.item.id for result in search_results]
        bucket = self.bucket_classifier.classify(case.query)
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
        return (
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
                bucket=bucket,
                top_result_kind=self._top_result_kind(search_results),
                first_relevant_kind=self._first_relevant_kind(search_results, case.expected),
                file_hit=bool(file_metrics["file_hit"]),
                file_reciprocal_rank=float(file_metrics["file_mrr"]),
                file_precision_at_r=float(file_metrics["file_precision_at_r"]),
                file_recall=float(file_metrics["file_recall"]),
                ndcg=float(file_metrics["ndcg"]),
                average_precision=float(file_metrics["average_precision"]),
            ),
            duration_ms,
        )

    def _top_result_kind(self, search_results: list[Any]) -> str:
        if not search_results:
            return "none"
        result = search_results[0]
        winning_index_kind = result.item.metadata.get("winning_index_kind")
        return winning_index_kind if winning_index_kind is not None else self.index_kind_resolver.resolve(result.item)

    def _first_relevant_kind(self, search_results: list[Any], expected: list[str]) -> str:
        for result in search_results:
            if self._matches_any_expected(result.item, expected):
                winning_index_kind = result.item.metadata.get("winning_index_kind")
                return winning_index_kind if winning_index_kind is not None else self.index_kind_resolver.resolve(result.item)
        return "none"

    def _bucket_metrics(self, results: list[EvalResult], limit: int) -> dict[str, Any]:
        by_bucket: dict[str, list[EvalResult]] = defaultdict(list)
        for result in results:
            by_bucket[result.bucket].append(result)
        metrics: dict[str, Any] = {}
        for bucket, bucket_results in sorted(by_bucket.items()):
            prefix = f"bucket.{bucket}"
            metrics[f"{prefix}.cases"] = len(bucket_results)
            metrics[f"{prefix}.hit_rate@{limit}"] = self._mean(1.0 if result.hit else 0.0 for result in bucket_results)
            metrics[f"{prefix}.hit_rate@1"] = self._mean(1.0 if self._hit_at(result, 1) else 0.0 for result in bucket_results)
            metrics[f"{prefix}.hit_rate@3"] = self._mean(1.0 if self._hit_at(result, 3) else 0.0 for result in bucket_results)
            metrics[f"{prefix}.hit_rate@5"] = self._mean(1.0 if self._hit_at(result, 5) else 0.0 for result in bucket_results)
            metrics[f"{prefix}.file_hit_rate@1"] = self._mean(
                1.0 if self._file_hit_at(result, 1) else 0.0 for result in bucket_results
            )
            metrics[f"{prefix}.file_hit_rate@3"] = self._mean(
                1.0 if self._file_hit_at(result, 3) else 0.0 for result in bucket_results
            )
            metrics[f"{prefix}.file_hit_rate@5"] = self._mean(
                1.0 if self._file_hit_at(result, 5) else 0.0 for result in bucket_results
            )
            metrics[f"{prefix}.file_hit_rate@{limit}"] = self._mean(
                1.0 if result.file_hit else 0.0 for result in bucket_results
            )
            metrics[f"{prefix}.file_mrr@{limit}"] = self._mean(
                result.file_reciprocal_rank for result in bucket_results
            )
            metrics[f"{prefix}.file_precision@R"] = self._mean(
                result.file_precision_at_r for result in bucket_results
            )
            metrics[f"{prefix}.file_recall@{limit}"] = self._mean(result.file_recall for result in bucket_results)
            metrics[f"{prefix}.ndcg@{limit}"] = self._mean(result.ndcg for result in bucket_results)
            metrics[f"{prefix}.map@{limit}"] = self._mean(result.average_precision for result in bucket_results)
        return metrics

    def _item_kind_metrics(self, results: list[EvalResult]) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        total = max(len(results), 1)
        hit_count = max(sum(1 for result in results if result.first_relevant_kind != "none"), 1)
        top_counts = Counter(result.top_result_kind for result in results)
        relevant_counts = Counter(result.first_relevant_kind for result in results)
        for kind, count in sorted(top_counts.items()):
            metrics[f"top_result_kind.{kind}.rate"] = count / total
        for kind, count in sorted(relevant_counts.items()):
            if kind == "none":
                metrics["first_relevant_kind.none.rate"] = count / total
                continue
            metrics[f"first_relevant_kind.{kind}.rate"] = count / hit_count
        return metrics

    def _derived_metrics(
        self,
        results: list[EvalResult],
        limit: int,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        mean_ms = float(metrics.get("search_duration_ms_mean", 0.0) or 0.0)
        mean_seconds = mean_ms / 1000
        return {
            "expected_files_mean": self._mean(len(result.expected) for result in results),
            "expected_files_p95": self._percentile([float(len(result.expected)) for result in results], 0.95),
            "multi_expected_rate": self._mean(1.0 if len(result.expected) > 1 else 0.0 for result in results),
            "retrieved_files_mean": self._mean(len(result.retrieved_files or []) for result in results),
            f"unique_file_ratio@{limit}": self._mean(
                len(result.retrieved_files or []) / max(len(result.retrieved), 1) for result in results
            ),
            "miss_rate@1": 1.0 - float(metrics.get("hit_rate@1", 0.0) or 0.0),
            f"miss_rate@{limit}": 1.0 - float(metrics.get(f"hit_rate@{limit}", 0.0) or 0.0),
            f"file_miss_rate@{limit}": 1.0 - float(metrics.get(f"file_hit_rate@{limit}", 0.0) or 0.0),
            f"coverage_gap@{limit}": 1.0 - float(metrics.get(f"recall@{limit}", 0.0) or 0.0),
            f"file_coverage_gap@{limit}": 1.0 - float(metrics.get(f"file_recall@{limit}", 0.0) or 0.0),
            "rerank_headroom@3": float(metrics.get("hit_rate@3", 0.0) or 0.0)
            - float(metrics.get("hit_rate@1", 0.0) or 0.0),
            "rerank_headroom@5": float(metrics.get("hit_rate@5", 0.0) or 0.0)
            - float(metrics.get("hit_rate@1", 0.0) or 0.0),
            f"rerank_headroom@{limit}": float(metrics.get(f"hit_rate@{limit}", 0.0) or 0.0)
            - float(metrics.get("hit_rate@1", 0.0) or 0.0),
            f"bundle_complete_rate@{limit}": self._mean(1.0 if result.file_recall >= 1.0 else 0.0 for result in results),
            f"bundle_partial_rate@{limit}": self._mean(
                1.0 if 0.0 < result.file_recall < 1.0 else 0.0 for result in results
            ),
            f"bundle_empty_rate@{limit}": self._mean(1.0 if result.file_recall <= 0.0 else 0.0 for result in results),
            f"ndcg_per_second@{limit}": self._per_second(float(metrics.get(f"ndcg@{limit}", 0.0) or 0.0), mean_seconds),
            f"map_per_second@{limit}": self._per_second(float(metrics.get(f"map@{limit}", 0.0) or 0.0), mean_seconds),
            f"recall_per_second@{limit}": self._per_second(
                float(metrics.get(f"recall@{limit}", 0.0) or 0.0),
                mean_seconds,
            ),
        }

    def _statistical_metrics(
        self,
        results: list[EvalResult],
        durations_ms: list[float],
        limit: int,
    ) -> dict[str, float]:
        stats: dict[str, float] = {}
        series: list[tuple[str, Any, bool]] = [
            (f"hit_rate@{limit}", (1.0 if result.hit else 0.0 for result in results), True),
            (f"mrr@{limit}", (result.reciprocal_rank for result in results), False),
            (f"precision@{limit}", (result.precision for result in results), False),
            (f"recall@{limit}", (result.recall for result in results), False),
            ("hit_rate@1", (1.0 if self._hit_at(result, 1) else 0.0 for result in results), True),
            ("hit_rate@3", (1.0 if self._hit_at(result, 3) else 0.0 for result in results), True),
            ("hit_rate@5", (1.0 if self._hit_at(result, 5) else 0.0 for result in results), True),
            ("file_hit_rate@1", (1.0 if self._file_hit_at(result, 1) else 0.0 for result in results), True),
            ("file_hit_rate@3", (1.0 if self._file_hit_at(result, 3) else 0.0 for result in results), True),
            ("file_hit_rate@5", (1.0 if self._file_hit_at(result, 5) else 0.0 for result in results), True),
            (f"file_hit_rate@{limit}", (1.0 if result.file_hit else 0.0 for result in results), True),
            (f"file_mrr@{limit}", (result.file_reciprocal_rank for result in results), False),
            ("file_precision@R", (result.file_precision_at_r for result in results), False),
            (f"file_recall@{limit}", (result.file_recall for result in results), False),
            (f"ndcg@{limit}", (result.ndcg for result in results), False),
            (f"map@{limit}", (result.average_precision for result in results), False),
            ("search_duration_ms_mean", durations_ms, False),
        ]
        for name, values, binary in series:
            stats.update(self.statistics.summarize(name, values, binary=binary))
        return stats

    def _matches_any_expected(self, item: object, expected: list[str]) -> bool:
        return any(self._matches_expected(item, value) for value in expected)

    def _matches_expected(self, item: object, expected: str) -> bool:
        normalized = expected.strip()
        if normalized.startswith("glob:"):
            pattern = normalized.removeprefix("glob:")
            return fnmatch.fnmatchcase(str(item.path), pattern) or fnmatch.fnmatchcase(str(item.id), pattern)
        return (
            item.id == normalized
            or item.path == normalized
            or item.path.startswith(normalized.rstrip("/") + "/")
            or item.id.startswith(normalized + "#")
        )

    def _file_metrics(self, search_results: list[Any], expected: list[str], limit: int) -> dict[str, Any]:
        files = self._dedupe_files(result.item.path for result in search_results[:limit])
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
        if normalized.startswith("glob:"):
            return fnmatch.fnmatchcase(path, normalized.removeprefix("glob:"))
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

    def _file_hit_at(self, result: EvalResult, limit: int) -> bool:
        return any(self._matches_any_path_expected(value, result.expected) for value in result.retrieved_files[:limit])

    def _matches_path_or_id(self, value: str, expected: list[str]) -> bool:
        return any(
            (item.startswith("glob:") and fnmatch.fnmatchcase(value.split("#", 1)[0].split("::", 1)[0], item.removeprefix("glob:"))) or value == item or value.startswith((item + "#", item + "::", item.rstrip("/") + "/"))
            for item in expected
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
        index = min(round((len(ordered) - 1) * quantile), len(ordered) - 1)
        return ordered[index]

    def _per_second(self, value: float, seconds: float) -> float:
        if seconds <= 0:
            return 0.0
        return value / seconds
