from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from ..explanation.jsonish_parser import JsonishParser
from ..domain import SearchResult
from ..generation import GenerationProvider
from ..strategies import RetrievalStrategy
from .answer_candidate_reranker import AnswerCandidateReranker
from .answer_case import AnswerCase
from .answer_context_builder import AnswerContextBuilder
from .answer_judge import AnswerJudge
from .answer_metrics import AnswerMetrics
from .answer_query_planner import AnswerQueryPlanner


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
    progress_callback: Callable[[int, int, AnswerCase], None] | None = None
    row_callback: Callable[[int, int, dict[str, Any]], None] | None = None
    parser: JsonishParser = field(default_factory=JsonishParser)

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
            retrieval_started = perf_counter()
            search_results, plan_payload, planning_usage, planning_model, rerank_usage, rerank_model = self._retrieve(case)
            retrieval_duration_ms = (perf_counter() - retrieval_started) * 1000
            context_started = perf_counter()
            context = self.context_builder.build(search_results)
            context_duration_ms = (perf_counter() - context_started) * 1000
            retrieved_files = [search_result.item.path for search_result in search_results]
            base_metrics = AnswerMetrics().score("", case.reference)
            base_metrics.update(self._file_bundle_metrics(retrieved_files, case.expected_paths, prefix="candidate"))
            base_metrics.update(self._file_bundle_metrics(context.files, case.expected_paths, prefix="context"))
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
            generation_started = perf_counter()
            result = self.answer_provider.generate_json_result(self._answer_prompt(case, context.text))
            generation_duration_ms = (perf_counter() - generation_started) * 1000
            raw_prediction = result.text
            try:
                payload = self.parser.parse_object(raw_prediction)
            except Exception as exc:
                base_metrics["generation_duration_ms"] = generation_duration_ms
                return {
                    "row": {
                        "case_id": case.id,
                        "question": case.question,
                        "reference": case.reference,
                        "prediction": "",
                        "raw_prediction": raw_prediction,
                        "retrieved_files": retrieved_files,
                        "context_files": context.files,
                        "context_errors": context.errors,
                        "expected_paths": case.expected_paths,
                        "metadata": case.metadata,
                        "query_plan": plan_payload,
                        "generation_model": result.model,
                        "metrics": base_metrics,
                        "error": str(exc),
                        "duration_ms": (perf_counter() - started) * 1000,
                    },
                    "usage": {
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "total_tokens": result.total_tokens,
                    },
                    "generation_model": result.model,
                    "planning_usage": planning_usage,
                    "planning_model": planning_model,
                    "rerank_usage": rerank_usage,
                    "rerank_model": rerank_model,
                    "judge_usage": None,
                    "judge_model": None,
                    "error": 1,
                    "judge_error": 0,
                }
            answer = str(payload.get("answer") or "").strip()
            citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
            metrics = AnswerMetrics().score(answer, case.reference)
            metrics.update(self._file_bundle_metrics(retrieved_files, case.expected_paths, prefix="candidate"))
            metrics.update(self._file_bundle_metrics(context.files, case.expected_paths, prefix="context"))
            metrics.update(self._citation_metrics(citations, context.file_ranges))
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
                "expected_paths": case.expected_paths,
                "metadata": case.metadata,
                "query_plan": plan_payload,
                "generation_model": result.model,
                "metrics": metrics,
                "duration_ms": (perf_counter() - started) * 1000,
            }
            judge_usage = None
            judge_model = None
            judge_error = 0
            if self.judge is not None:
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
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                },
                "generation_model": result.model,
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
            return {
                "row": {
                    "case_id": case.id,
                    "question": case.question,
                    "reference": case.reference,
                    "prediction": "",
                    "raw_prediction": raw_prediction,
                    "expected_paths": case.expected_paths,
                    "metadata": case.metadata,
                    "metrics": AnswerMetrics().score("", case.reference),
                    "error": str(exc),
                    "duration_ms": (perf_counter() - started) * 1000,
                },
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

    def _retrieve(
        self,
        case: AnswerCase,
    ) -> tuple[list[SearchResult], dict[str, Any], dict[str, int] | None, str | None, dict[str, int] | None, str | None]:
        if self.query_planner is None:
            return (
                self.retrieval_strategy.search(case.question, self.limit),
                {"mode": "single_query", "queries": [case.question], "duration_ms": 0.0},
                None,
                None,
                None,
                None,
            )
        started = perf_counter()
        plan, result = self.query_planner.plan_result(case)
        plan_payload = {
            "mode": "llm_multi_query",
            "queries": plan.queries,
            "rationale": plan.rationale,
            "duration_ms": (perf_counter() - started) * 1000,
        }
        usage = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
        }
        rerank_candidate_limit = self.query_result_reranker.candidate_limit if self.query_result_reranker else self.limit
        query_limit = max(self.limit, rerank_candidate_limit, 1)
        worker_count = max(1, min(int(self.query_workers or 1), len(plan.queries)))
        probe_strategy = self.query_retrieval_strategy or self.retrieval_strategy
        if worker_count == 1:
            result_sets = [probe_strategy.search(query, query_limit) for query in plan.queries]
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(probe_strategy.search, query, query_limit) for query in plan.queries]
                result_sets = [future.result() for future in futures]
        merged = self._merge_query_results(result_sets, query_limit)
        if self.query_result_reranker is None:
            return merged[: self.limit], plan_payload, usage, result.model, None, None
        reranked, rerank_payload = self.query_result_reranker.rerank(case.question, merged, self.limit)
        plan_payload["final_rerank"] = rerank_payload
        rerank_usage = {
            "input_tokens": int(rerank_payload.get("input_tokens") or 0),
            "output_tokens": int(rerank_payload.get("output_tokens") or 0),
            "total_tokens": int(rerank_payload.get("total_tokens") or 0),
        }
        rerank_model = str(rerank_payload.get("model") or "")
        return reranked, plan_payload, usage, result.model, rerank_usage, rerank_model

    def _merge_query_results(self, result_sets: list[list[SearchResult]], limit: int) -> list[SearchResult]:
        best_by_file: dict[str, SearchResult] = {}
        for query_index, results in enumerate(result_sets):
            query_boost = 1.0 / (query_index + 1)
            for rank, result in enumerate(results, start=1):
                file_key = self._normalize_path(result.item.path)
                rank_score = 1.0 / rank
                merged_score = float(result.score) + rank_score + (0.05 * query_boost)
                existing = best_by_file.get(file_key)
                if existing is None or merged_score > existing.score:
                    best_by_file[file_key] = SearchResult(result.item, merged_score)
        return sorted(best_by_file.values(), key=lambda item: item.score, reverse=True)[:limit]

    def _answer_prompt(self, case: AnswerCase, context: str) -> str:
        repository_context = self.repository_context.strip()
        context_section = ""
        if repository_context:
            context_section = f"""
Repository orientation:
{repository_context}

"""
        return f"""Answer the developer's repository question using only the provided retrieval context.

Requirements:
- Explain the code behavior, not only where it is.
- Cite relative file paths and line numbers from the context for important claims.
- If the context is insufficient, say what is missing instead of inventing behavior.
- Return JSON only: {{"answer":"...","citations":[{{"path":"...","lines":"...","reason":"..."}}],"confidence":0.0}}

{context_section}
Question:
{case.question}

Case metadata:
{json.dumps(case.metadata, ensure_ascii=False)}

Retrieved context:
{context}
"""

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
        metrics = {
            f"{prefix}_file_hit": 1.0 if first_rank else 0.0,
            f"{prefix}_file_mrr": (1.0 / first_rank) if first_rank else 0.0,
            f"{prefix}_file_recall": self._file_recall(normalized_files, normalized_expected),
            f"{prefix}_file_precision": self._file_precision(normalized_files, normalized_expected),
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
