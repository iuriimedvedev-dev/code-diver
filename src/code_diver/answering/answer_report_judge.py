from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from ..domain import CodeItem, SearchResult
from .answer_case import AnswerCase
from .answer_context_builder import AnswerContextBuilder
from .answer_judge import AnswerJudge
from .answer_metrics import AnswerMetrics


@dataclass(slots=True)
class AnswerReportJudge:
    judge: AnswerJudge
    root: Path | None = None
    context_files: int = 4
    context_lines: int = 160
    max_file_bytes: int = 1_000_000
    workers: int = 1
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None
    row_callback: Callable[[int, int, dict[str, Any]], None] | None = None

    def judge_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = [row for row in payload.get("results") or [] if isinstance(row, dict)]
        started = perf_counter()
        judged_rows: list[dict[str, Any] | None] = [None] * len(rows)
        usage = self._empty_usage()
        errors = 0
        worker_count = max(1, min(int(self.workers or 1), max(len(rows), 1)))
        if worker_count == 1:
            for index, row in enumerate(rows, start=1):
                result = self._judge_row(row)
                judged_rows[index - 1] = result["row"]
                errors += int(result["error"])
                if result["usage"] is not None:
                    self._merge_usage(usage, result["model"], result["usage"])
                self._notify(index, len(rows), result["row"])
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(self._judge_row, row): index
                    for index, row in enumerate(rows, start=1)
                }
                completed = 0
                for future in as_completed(futures):
                    index = futures[future]
                    result = future.result()
                    completed += 1
                    judged_rows[index - 1] = result["row"]
                    errors += int(result["error"])
                    if result["usage"] is not None:
                        self._merge_usage(usage, result["model"], result["usage"])
                    self._notify(completed, len(rows), result["row"])
        final_rows = [row for row in judged_rows if row is not None]
        metrics = AnswerMetrics().aggregate(final_rows)
        metrics["cases"] = float(len(final_rows))
        judged = dict(payload)
        judged["results"] = final_rows
        judged["metrics"] = metrics
        judged["judge_usage"] = usage
        judged["judge_error_count"] = errors
        judged["posthoc_judge"] = {
            "enabled": True,
            "model": self.judge.provider.model,
            "prompt": str(self.judge.prompt_path),
            "duration_ms": (perf_counter() - started) * 1000,
            "workers": worker_count,
            "context_reconstructed": any(not row.get("context_text") for row in rows),
        }
        return judged

    def _judge_row(self, row: dict[str, Any]) -> dict[str, Any]:
        updated = dict(row)
        case = self._case_from_row(row)
        context = self._context_for_row(row)
        prediction = str(row.get("prediction") or "")
        try:
            started = perf_counter()
            judged = self.judge.judge(case, prediction, context)
            metrics = dict(updated.get("metrics") or {})
            metrics.update(judged["scores"])
            metrics["judge_duration_ms"] = (perf_counter() - started) * 1000
            updated["metrics"] = metrics
            updated["judge"] = judged
            updated.pop("judge_error", None)
            return {
                "row": updated,
                "usage": judged["usage"],
                "model": judged["model"],
                "error": 0,
            }
        except Exception as exc:
            updated["judge_error"] = str(exc)
            metrics = dict(updated.get("metrics") or {})
            metrics["judge_duration_ms"] = 0.0
            updated["metrics"] = metrics
            return {"row": updated, "usage": None, "model": None, "error": 1}

    def _case_from_row(self, row: dict[str, Any]) -> AnswerCase:
        return AnswerCase.from_json(
            {
                "case_id": row.get("case_id"),
                "question": row.get("question"),
                "reference": row.get("reference"),
                "expected_paths": row.get("expected_paths") or [],
                "metadata": row.get("metadata") or {},
            }
        )

    def _context_for_row(self, row: dict[str, Any]) -> str:
        context_text = str(row.get("context_text") or "").strip()
        if context_text:
            return context_text
        if self.root is None:
            return ""
        paths = [str(path) for path in row.get("retrieved_files") or row.get("context_files") or []]
        results = [
            SearchResult(
                CodeItem(
                    id=f"{path}::{rank}",
                    path=path,
                    title=path,
                    content="",
                    start_line=1,
                    metadata={"index_kind": self._index_kind(path)},
                ),
                1.0 / rank,
            )
            for rank, path in enumerate(paths, start=1)
        ]
        return AnswerContextBuilder(
            self.root,
            max_files=self.context_files,
            lines_per_file=self.context_lines,
            max_file_bytes=self.max_file_bytes,
        ).build(results).text

    def _index_kind(self, path: str) -> str:
        normalized = path.lower()
        if normalized.endswith((".md", ".mdx", ".rst", ".txt", ".adoc")):
            return "doc_summary"
        return "file_summary"

    def _notify(self, completed: int, total: int, row: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(completed, total, row)
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

    def _merge_usage(
        self,
        target: dict[str, Any],
        model: str | None,
        usage: dict[str, Any],
    ) -> None:
        target["model_calls"] += 1
        target["input_tokens"] += int(usage.get("input_tokens") or 0)
        target["output_tokens"] += int(usage.get("output_tokens") or 0)
        target["total_tokens"] += int(usage.get("total_tokens") or 0)
        if model and model not in target["models"]:
            target["models"].append(model)

