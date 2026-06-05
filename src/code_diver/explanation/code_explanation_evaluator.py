from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from ..generation import GenerationProvider
from .explanation_case import ExplanationCase
from .explanation_judge import ExplanationJudge
from .explanation_metrics import ExplanationMetrics
from .jsonish_parser import JsonishParser


@dataclass(slots=True)
class CodeExplanationEvaluator:
    provider: GenerationProvider
    judge: ExplanationJudge | None = None
    progress_callback: Callable[[int, int, ExplanationCase], None] | None = None
    row_callback: Callable[[int, int, dict[str, Any]], None] | None = None
    workers: int = 1
    parser: JsonishParser = field(default_factory=JsonishParser)

    def evaluate(self, cases: list[ExplanationCase]) -> dict[str, Any]:
        metrics = ExplanationMetrics()
        total_usage = self._empty_usage()
        judge_usage = self._empty_usage()
        error_count = 0
        judge_error_count = 0
        started = perf_counter()
        total_cases = len(cases)
        rows_by_index: list[dict[str, Any] | None] = [None] * total_cases
        completed = 0
        worker_count = max(1, min(int(self.workers or 1), max(total_cases, 1)))
        if worker_count == 1:
            for index, case in enumerate(cases, start=1):
                result = self._evaluate_case(case, metrics)
                completed += 1
                rows_by_index[index - 1] = result["row"]
                error_count += int(result["error"])
                judge_error_count += int(result["judge_error"])
                self._merge_usage_dict(total_usage, result["generation_model"], result["usage"])
                if result["judge_usage"] is not None:
                    self._merge_usage_dict(judge_usage, result["judge_model"], result["judge_usage"])
                self._notify_progress(completed, total_cases, case, result["row"])
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(self._evaluate_case, case, metrics): (index, case)
                    for index, case in enumerate(cases, start=1)
                }
                for future in as_completed(futures):
                    index, case = futures[future]
                    result = future.result()
                    completed += 1
                    rows_by_index[index - 1] = result["row"]
                    error_count += int(result["error"])
                    judge_error_count += int(result["judge_error"])
                    self._merge_usage_dict(total_usage, result["generation_model"], result["usage"])
                    if result["judge_usage"] is not None:
                        self._merge_usage_dict(judge_usage, result["judge_model"], result["judge_usage"])
                    self._notify_progress(completed, total_cases, case, result["row"])
        rows = [row for row in rows_by_index if row is not None]
        aggregate = metrics.aggregate(rows)
        if self.judge is not None:
            judge_keys = sorted(
                {
                    key
                    for row in rows
                    for key in row.get("metrics", {})
                    if key.startswith("judge_")
                }
            )
            for key in judge_keys:
                aggregate[key] = sum(float(row["metrics"].get(key, 0.0)) for row in rows) / max(len(rows), 1)
        aggregate["cases"] = float(len(rows))
        aggregate["duration_ms"] = (perf_counter() - started) * 1000
        return {
            "metrics": aggregate,
            "usage": total_usage,
            "judge_usage": judge_usage if self.judge is not None else None,
            "error_count": error_count,
            "judge_error_count": judge_error_count if self.judge is not None else None,
            "results": rows,
        }

    def _evaluate_case(self, case: ExplanationCase, metrics: ExplanationMetrics) -> dict[str, Any]:
        case_started = perf_counter()
        prediction_text = ""
        empty_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        try:
            prediction_result = self.provider.generate_json_result(self._explanation_prompt(case))
            prediction_text = prediction_result.text
            prediction_payload = self._parse_json(prediction_text)
            generation_model = prediction_result.model
            usage = {
                "input_tokens": prediction_result.input_tokens,
                "output_tokens": prediction_result.output_tokens,
                "total_tokens": prediction_result.total_tokens,
            }
        except Exception as exc:
            return {
                "row": {
                    "case_id": case.id,
                    "metadata": case.metadata,
                    "prompt": case.prompt,
                    "reference": case.reference,
                    "prediction": "",
                    "raw_prediction": prediction_text,
                    "metrics": metrics.score("", case.reference),
                    "error": str(exc),
                    "duration_ms": (perf_counter() - case_started) * 1000,
                },
                "usage": empty_usage,
                "generation_model": getattr(self.provider, "model", "unknown"),
                "judge_usage": None,
                "judge_model": None,
                "error": 1,
                "judge_error": 0,
            }
        explanation = str(prediction_payload.get("explanation") or "").strip()
        row_metrics = metrics.score(explanation, case.reference)
        row: dict[str, Any] = {
            "case_id": case.id,
            "metadata": case.metadata,
            "prompt": case.prompt,
            "reference": case.reference,
            "prediction": explanation,
            "generation_model": generation_model,
            "metrics": row_metrics,
            "duration_ms": (perf_counter() - case_started) * 1000,
        }
        judge_usage = None
        judge_model = None
        judge_error = 0
        if self.judge is not None:
            try:
                judged = self.judge.judge(case, explanation)
                row["judge"] = judged
                row_metrics.update(judged["scores"])
                judge_usage = judged["usage"]
                judge_model = judged["model"]
            except Exception as exc:
                judge_error = 1
                row["judge_error"] = str(exc)
        return {
            "row": row,
            "usage": usage,
            "generation_model": generation_model,
            "judge_usage": judge_usage,
            "judge_model": judge_model,
            "error": 0,
            "judge_error": judge_error,
        }

    def _notify_progress(
        self,
        completed: int,
        total_cases: int,
        case: ExplanationCase,
        row: dict[str, Any],
    ) -> None:
        if self.progress_callback is not None:
            self.progress_callback(completed, total_cases, case)
        if self.row_callback is not None:
            self.row_callback(completed, total_cases, row)

    def _explanation_prompt(self, case: ExplanationCase) -> str:
        return f"""Explain the following code for a developer.

Requirements:
- Explain the purpose in plain language.
- Mention important inputs, outputs, side effects, and control flow when visible.
- Be specific to the shown code.
- Do not invent dependencies or behavior that is not in the code.
- Return JSON only: {{"explanation": "..."}}

User prompt:
{case.prompt}

Metadata:
{json.dumps(case.metadata, ensure_ascii=False)}

Code:
```python
{case.code}
```
"""

    def _parse_json(self, text: str) -> dict[str, Any]:
        return self.parser.parse_object(text)

    def _empty_usage(self) -> dict[str, Any]:
        return {
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "models": [],
        }

    def _merge_usage(self, target: dict[str, Any], model: str, result: Any) -> None:
        self._merge_usage_dict(
            target,
            model,
            {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
        )

    def _merge_usage_dict(self, target: dict[str, Any], model: str, usage: dict[str, Any]) -> None:
        target["model_calls"] += 1
        target["input_tokens"] += int(usage.get("input_tokens") or 0)
        target["output_tokens"] += int(usage.get("output_tokens") or 0)
        target["total_tokens"] += int(usage.get("total_tokens") or 0)
        if model not in target["models"]:
            target["models"].append(model)
