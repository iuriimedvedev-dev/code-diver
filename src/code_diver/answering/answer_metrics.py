from __future__ import annotations

from statistics import mean
from typing import Any

from ..explanation import ExplanationMetrics


class AnswerMetrics:
    def __init__(self):
        self.text_metrics = ExplanationMetrics()

    def score(self, prediction: str, reference: str) -> dict[str, float]:
        return self.text_metrics.score(prediction, reference)

    def aggregate(self, rows: list[dict[str, Any]]) -> dict[str, float]:
        metric_keys = sorted(
            {
                key
                for row in rows
                for key, value in (row.get("metrics") or {}).items()
                if isinstance(value, (int, float))
            }
        )
        return {
            key: mean(float((row.get("metrics") or {}).get(key, 0.0)) for row in rows)
            for key in metric_keys
        }
