from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from ..generation import GenerationProvider
from ..generation.jsonish_parser import JsonishParser
from ..strategies import RetrievalStrategy
from .answer_candidate_reranker import AnswerCandidateReranker
from .answer_case import AnswerCase
from .answer_context_builder import AnswerContextBuilder
from .answer_grounding_metrics import AnswerGroundingMetrics
from .answer_judge import AnswerJudge
from .answer_metrics import AnswerMetrics
from .answer_query_planner import AnswerQueryPlanner
from .answer_report_integrity import assert_case_count_matches, stamp_case_counts
from .answer_service import AnswerService
from .unjudgeable_row_policy import REASON_GENERATION_ERROR, synthesize_judgment, unjudgeable_reason


@dataclass(slots=True)
class AnswerEvaluator:
    retrieval_strategy: RetrievalStrategy
    answer_provider: GenerationProvider
    context_builder: AnswerContextBuilder
    judge: AnswerJudge | None = None
    query_planner: AnswerQueryPlanner | None = None
    query_retrieval_strategy: RetrievalStrategy | None = None
    query_result_reranker: AnswerCandidateReranker | None = None
    repository_context: str = ""
    limit: int = 10
    query_workers: int = 4
    workers: int = 1
    save_context: bool = True
    restrict_citations_to_context: bool = False
    progress_callback: Callable[[int, int, AnswerCase], None] | None = None
    row_callback: Callable[[int, int, dict[str, Any]], None] | None = None
    parser: JsonishParser = field(default_factory=JsonishParser)
    # Built from the fields above so existing callers keep their signature. Answering lives in
    # the service; this class only scores what the service produced.
    service: AnswerService | None = None

    def __post_init__(self) -> None:
        if self.service is None:
            self.service = AnswerService(
                retrieval_strategy=self.retrieval_strategy,
                answer_provider=self.answer_provider,
                context_builder=self.context_builder,
                query_planner=self.query_planner,
                query_retrieval_strategy=self.query_retrieval_strategy,
                query_result_reranker=self.query_result_reranker,
                repository_context=self.repository_context,
                limit=self.limit,
                query_workers=self.query_workers,
                restrict_citations_to_context=self.restrict_citations_to_context,
                parser=self.parser,
            )

    def evaluate(self, cases: list[AnswerCase]) -> dict[str, Any]:
        started = perf_counter()
        rows_by_index: list[dict[str, Any] | None] = [None] * len(cases)
        usage = self._empty_usage()
        planning_usage = self._empty_usage()
        rerank_usage = self._empty_usage()
        judge_usage = self._empty_usage()
        errors = 0
        judge_errors = 0
        worker_count = max(1, min(int(self.workers or 1), max(len(cases), 1)))
        completed = 0
        if worker_count == 1:
            for index, case in enumerate(cases, start=1):
                result = self._evaluate_case(case)
                completed += 1
                rows_by_index[index - 1] = result["row"]
                errors += int(result["error"])
                judge_errors += int(result["judge_error"])
                self._merge_usage_dict(usage, result["generation_model"], result["usage"])
                if result["planning_usage"] is not None:
                    self._merge_usage_dict(planning_usage, result["planning_model"], result["planning_usage"])
                if result["rerank_usage"] is not None:
                    self._merge_usage_dict(rerank_usage, result["rerank_model"], result["rerank_usage"])
                if result["judge_usage"] is not None:
                    self._merge_usage_dict(judge_usage, result["judge_model"], result["judge_usage"])
                self._notify_progress(completed, len(cases), case, result["row"])
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(self._evaluate_case, case): (index, case)
                    for index, case in enumerate(cases, start=1)
                }
                for future in as_completed(futures):
                    index, case = futures[future]
                    result = future.result()
                    completed += 1
                    rows_by_index[index - 1] = result["row"]
                    errors += int(result["error"])
                    judge_errors += int(result["judge_error"])
                    self._merge_usage_dict(usage, result["generation_model"], result["usage"])
                    if result["planning_usage"] is not None:
                        self._merge_usage_dict(planning_usage, result["planning_model"], result["planning_usage"])
                    if result["rerank_usage"] is not None:
                        self._merge_usage_dict(rerank_usage, result["rerank_model"], result["rerank_usage"])
                    if result["judge_usage"] is not None:
                        self._merge_usage_dict(judge_usage, result["judge_model"], result["judge_usage"])
                    self._notify_progress(completed, len(cases), case, result["row"])
        rows = [row for row in rows_by_index if row is not None]
        metrics = AnswerMetrics().aggregate(rows)
        metrics["cases"] = float(len(rows))
        stamp_case_counts(metrics, case_count_requested=len(cases), row_count=len(rows))
        assert_case_count_matches(
            case_count_requested=len(cases), row_count=len(rows), context="AnswerEvaluator.evaluate"
        )
        metrics["answer_duration_ms_total"] = (perf_counter() - started) * 1000
        metrics["answer_duration_ms_mean"] = metrics["answer_duration_ms_total"] / max(len(rows), 1)
        return {
            "metrics": metrics,
            "usage": usage,
            "planning_usage": planning_usage if self.query_planner is not None else None,
            "rerank_usage": rerank_usage if self.query_result_reranker is not None else None,
            "judge_usage": judge_usage if self.judge is not None else None,
            "error_count": errors,
            "judge_error_count": judge_errors if self.judge is not None else None,
            "results": rows,
        }

    def _evaluate_case(self, case: AnswerCase) -> dict[str, Any]:
        started = perf_counter()
        raw_prediction = ""
        empty_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        try:
            outcome = self._service().answer_case(case)
            plan_payload = outcome.query_plan
            planning_usage = outcome.planning_usage
            planning_model = outcome.planning_model
            rerank_usage = outcome.rerank_usage
            rerank_model = outcome.rerank_model
            retrieval_duration_ms = outcome.retrieval_duration_ms
            context_duration_ms = outcome.context_duration_ms
            context = outcome.context
            retrieved_files = outcome.retrieved_files
            base_metrics = AnswerMetrics().score("", case.reference)
            base_metrics.update(self._file_bundle_metrics(retrieved_files, case.expected_paths, prefix="candidate"))
            base_metrics.update(self._file_bundle_metrics(context.files, case.expected_paths, prefix="context"))
            # Scored with an empty answer so a case that later fails to parse still carries
            # every grounding key. Aggregation would otherwise read a missing key as 0.0
            # anyway, but only after the key exists in some other row.
            base_metrics.update(AnswerGroundingMetrics().score("", [], context.files, case.expected_paths))
            base_metrics.update(
                {
                    "retrieval_duration_ms": retrieval_duration_ms,
                    "planning_duration_ms": float(plan_payload.get("duration_ms") or 0.0),
                    "planned_query_count": float(len(plan_payload.get("queries") or [case.question])),
                    "rerank_duration_ms": float((plan_payload.get("final_rerank") or {}).get("duration_ms") or 0.0),
                    "context_duration_ms": context_duration_ms,
                    "generation_duration_ms": 0.0,
                    "judge_duration_ms": 0.0,
                    "retrieved_files_count": float(len(retrieved_files)),
                    "context_files_count": float(len(context.files)),
                    "context_error_count": float(len(context.errors)),
                }
            )
            generation_duration_ms = outcome.generation_duration_ms
            raw_prediction = outcome.raw_prediction
            if outcome.parse_error is not None:
                base_metrics["generation_duration_ms"] = generation_duration_ms
                parse_failure_row: dict[str, Any] = {
                    "case_id": case.id,
                    "question": case.question,
                    "reference": case.reference,
                    "prediction": "",
                    "raw_prediction": raw_prediction,
                    "retrieved_files": retrieved_files,
                    "context_files": context.files,
                    "context_errors": context.errors,
                    "context_text": context.text if self.save_context else "",
                    "expected_paths": case.expected_paths,
                    "metadata": case.metadata,
                    "query_plan": plan_payload,
                    "generation_model": outcome.generation_model,
                    "metrics": base_metrics,
                    "error": outcome.parse_error,
                    "duration_ms": (perf_counter() - started) * 1000,
                }
                if self.judge is not None:
                    judged = synthesize_judgment(REASON_GENERATION_ERROR)
                    parse_failure_row["judge"] = judged
                    base_metrics.update(judged["scores"])
                return {
                    "row": parse_failure_row,
                    "usage": outcome.usage,
                    "generation_model": outcome.generation_model,
                    "planning_usage": planning_usage,
                    "planning_model": planning_model,
                    "rerank_usage": rerank_usage,
                    "rerank_model": rerank_model,
                    "judge_usage": None,
                    "judge_model": None,
                    "error": 1,
                    "judge_error": 0,
                }
            answer = outcome.answer
            citations = outcome.citations
            metrics = AnswerMetrics().score(answer, case.reference)
            if outcome.confidence is not None:
                metrics["answer_confidence"] = outcome.confidence
            metrics.update(self._file_bundle_metrics(retrieved_files, case.expected_paths, prefix="candidate"))
            metrics.update(self._file_bundle_metrics(context.files, case.expected_paths, prefix="context"))
            metrics.update(self._citation_metrics(citations, context.file_ranges))
            metrics.update(
                AnswerGroundingMetrics().score(answer, citations, context.files, case.expected_paths)
            )
            metrics.update(
                {
                    "retrieval_duration_ms": retrieval_duration_ms,
                    "planning_duration_ms": float(plan_payload.get("duration_ms") or 0.0),
                    "planned_query_count": float(len(plan_payload.get("queries") or [case.question])),
                    "rerank_duration_ms": float((plan_payload.get("final_rerank") or {}).get("duration_ms") or 0.0),
                    "context_duration_ms": context_duration_ms,
                    "generation_duration_ms": generation_duration_ms,
                    "judge_duration_ms": 0.0,
                    "retrieved_files_count": float(len(retrieved_files)),
                    "context_files_count": float(len(context.files)),
                    "context_error_count": float(len(context.errors)),
                }
            )
            row: dict[str, Any] = {
                "case_id": case.id,
                "question": case.question,
                "reference": case.reference,
                "prediction": answer,
                "citations": citations,
                "retrieved_files": retrieved_files,
                "context_files": context.files,
                "context_errors": context.errors,
                "context_text": context.text if self.save_context else "",
                "expected_paths": case.expected_paths,
                "metadata": case.metadata,
                "query_plan": plan_payload,
                "generation_model": outcome.generation_model,
                "metrics": metrics,
                "duration_ms": (perf_counter() - started) * 1000,
            }
            judge_usage = None
            judge_model = None
            judge_error = 0
            if self.judge is not None:
                unjudgeable = unjudgeable_reason(row)
                if unjudgeable is not None:
                    judged = synthesize_judgment(unjudgeable)
                    metrics["judge_duration_ms"] = 0.0
                    row["judge"] = judged
                    row["metrics"].update(judged["scores"])
                else:
                    try:
                        judge_started = perf_counter()
                        judged = self.judge.judge(case, answer, context.text)
                        metrics["judge_duration_ms"] = (perf_counter() - judge_started) * 1000
                        row["judge"] = judged
                        row["metrics"].update(judged["scores"])
                        judge_usage = judged["usage"]
                        judge_model = judged["model"]
                    except Exception as exc:
                        judge_error = 1
                        row["judge_error"] = str(exc)
            return {
                "row": row,
                "usage": outcome.usage,
                "generation_model": outcome.generation_model,
                "planning_usage": planning_usage,
                "planning_model": planning_model,
                "rerank_usage": rerank_usage,
                "rerank_model": rerank_model,
                "judge_usage": judge_usage,
                "judge_model": judge_model,
                "error": 0,
                "judge_error": judge_error,
            }
        except Exception as exc:
            failure_metrics = AnswerMetrics().score("", case.reference)
            failure_row: dict[str, Any] = {
                "case_id": case.id,
                "question": case.question,
                "reference": case.reference,
                "prediction": "",
                "raw_prediction": raw_prediction,
                "expected_paths": case.expected_paths,
                "metadata": case.metadata,
                "metrics": failure_metrics,
                "error": str(exc),
                "duration_ms": (perf_counter() - started) * 1000,
            }
            if self.judge is not None:
                judged = synthesize_judgment(REASON_GENERATION_ERROR)
                failure_row["judge"] = judged
                failure_metrics.update(judged["scores"])
            return {
                "row": failure_row,
                "usage": empty_usage,
                "generation_model": getattr(self.answer_provider, "model", "unknown"),
                "planning_usage": None,
                "planning_model": None,
                "rerank_usage": None,
                "rerank_model": None,
                "judge_usage": None,
                "judge_model": None,
                "error": 1,
                "judge_error": 0,
            }

    def _service(self) -> AnswerService:
        # __post_init__ always builds one; this keeps the type checker and the reader honest.
        if self.service is None:
            raise RuntimeError("AnswerEvaluator has no AnswerService.")
        return self.service

    def _file_bundle_metrics(
        self,
        files: list[str],
        expected_paths: list[str],
        *,
        prefix: str,
    ) -> dict[str, float]:
        if not expected_paths:
            return {}
        normalized_expected = {self._normalize_path(path) for path in expected_paths}
        normalized_files = self._dedupe_files([self._normalize_path(path) for path in files])
        first_rank = next(
            (index for index, path in enumerate(normalized_files, start=1) if path in normalized_expected),
            0,
        )
        recall = self._file_recall(normalized_files, normalized_expected)
        metrics = {
            f"{prefix}_file_hit": 1.0 if first_rank else 0.0,
            f"{prefix}_file_mrr": (1.0 / first_rank) if first_rank else 0.0,
            f"{prefix}_file_recall": recall,
            f"{prefix}_file_precision": self._file_precision(normalized_files, normalized_expected),
            # Partial recall is not a usable bundle for a multi-file question: the model is
            # asked to answer from files it was never shown. `*_file_hit` hides that by
            # scoring 1.0 as soon as one expected file makes it in.
            f"{prefix}_bundle_complete": 1.0 if recall >= 1.0 else 0.0,
        }
        if prefix == "candidate":
            metrics.update(
                {
                    "file_hit": metrics[f"{prefix}_file_hit"],
                    "file_recall": metrics[f"{prefix}_file_recall"],
                    "file_precision": metrics[f"{prefix}_file_precision"],
                    "file_mrr": metrics[f"{prefix}_file_mrr"],
                }
            )
        for k in (1, 3, 5, self.limit):
            if k <= 0:
                continue
            subset = normalized_files[:k]
            metrics[f"{prefix}_file_hit@{k}"] = 1.0 if any(path in normalized_expected for path in subset) else 0.0
            metrics[f"{prefix}_file_recall@{k}"] = self._file_recall(subset, normalized_expected)
            metrics[f"{prefix}_file_precision@{k}"] = self._file_precision(subset, normalized_expected)
        return metrics

    def _file_recall(self, files: list[str], expected_paths: set[str]) -> float:
        hits = {path for path in files if path in expected_paths}
        return len(hits) / max(len(expected_paths), 1)

    def _file_precision(self, files: list[str], expected_paths: set[str]) -> float:
        if not files:
            return 0.0
        hits = [path for path in files if path in expected_paths]
        return len(hits) / max(len(files), 1)

    def _normalize_path(self, path: str) -> str:
        return path.strip().lstrip("./")

    def _citation_metrics(self, citations: list[Any], file_ranges: dict[str, tuple[int, int]]) -> dict[str, float]:
        if not citations:
            return {
                "citation_count": 0.0,
                "citation_path_valid_rate": 0.0,
                "citation_line_valid_rate": 0.0,
            }
        path_hits = 0
        line_hits = 0
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            path = self._normalize_path(str(citation.get("path") or ""))
            if path not in file_ranges:
                continue
            path_hits += 1
            cited_range = self._line_range(str(citation.get("lines") or ""))
            if cited_range is None:
                continue
            context_start, context_end = file_ranges[path]
            if cited_range[0] <= context_end and cited_range[1] >= context_start:
                line_hits += 1
        total = len(citations)
        return {
            "citation_count": float(total),
            "citation_path_valid_rate": path_hits / max(total, 1),
            "citation_line_valid_rate": line_hits / max(total, 1),
        }

    def _line_range(self, value: str) -> tuple[int, int] | None:
        numbers = [int(match) for match in re.findall(r"\d+", value)]
        if not numbers:
            return None
        start = numbers[0]
        end = numbers[1] if len(numbers) > 1 else start
        if end < start:
            start, end = end, start
        return start, end

    def _dedupe_files(self, files: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for path in files:
            if path in seen:
                continue
            seen.add(path)
            deduped.append(path)
        return deduped

    def _notify_progress(self, completed: int, total: int, case: AnswerCase, row: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(completed, total, case)
        if self.row_callback is not None:
            self.row_callback(completed, total, row)

    def _empty_usage(self) -> dict[str, Any]:
        return {
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "models": [],
        }

    def _merge_usage_dict(self, target: dict[str, Any], model: str | None, usage: dict[str, Any]) -> None:
        target["model_calls"] += 1
        target["input_tokens"] += int(usage.get("input_tokens") or 0)
        target["output_tokens"] += int(usage.get("output_tokens") or 0)
        target["total_tokens"] += int(usage.get("total_tokens") or 0)
        if model and model not in target["models"]:
            target["models"].append(model)
