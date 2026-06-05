from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from ..generation import GenerationProvider
from .explanation_case import ExplanationCase
from .explanation_judge import ExplanationJudge
from .explanation_metrics import ExplanationMetrics


@dataclass(slots=True)
class CodeExplanationEvaluator:
    provider: GenerationProvider
    judge: ExplanationJudge | None = None
    progress_callback: Callable[[int, int, ExplanationCase], None] | None = None

    def evaluate(self, cases: list[ExplanationCase]) -> dict[str, Any]:
        metrics = ExplanationMetrics()
        rows: list[dict[str, Any]] = []
        total_usage = self._empty_usage()
        judge_usage = self._empty_usage()
        started = perf_counter()
        total_cases = len(cases)
        for index, case in enumerate(cases, start=1):
            case_started = perf_counter()
            prediction_result = self.provider.generate_json_result(self._explanation_prompt(case))
            prediction_payload = self._parse_json(prediction_result.text)
            explanation = str(prediction_payload.get("explanation") or "").strip()
            row_metrics = metrics.score(explanation, case.reference)
            self._merge_usage(total_usage, prediction_result.model, prediction_result)
            row: dict[str, Any] = {
                "case_id": case.id,
                "metadata": case.metadata,
                "prompt": case.prompt,
                "reference": case.reference,
                "prediction": explanation,
                "metrics": row_metrics,
                "duration_ms": (perf_counter() - case_started) * 1000,
            }
            if self.judge is not None:
                judged = self.judge.judge(case, explanation)
                row["judge"] = judged
                row_metrics.update(judged["scores"])
                self._merge_usage_dict(judge_usage, judged["model"], judged["usage"])
            rows.append(row)
            if self.progress_callback is not None:
                self.progress_callback(index, total_cases, case)
        aggregate = metrics.aggregate(rows)
        if self.judge is not None:
            judge_keys = [key for key in rows[0]["metrics"] if key.startswith("judge_")] if rows else []
            for key in judge_keys:
                aggregate[key] = sum(float(row["metrics"].get(key, 0.0)) for row in rows) / max(len(rows), 1)
        aggregate["cases"] = float(len(rows))
        aggregate["duration_ms"] = (perf_counter() - started) * 1000
        return {
            "metrics": aggregate,
            "usage": total_usage,
            "judge_usage": judge_usage if self.judge is not None else None,
            "results": rows,
        }

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
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise

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
