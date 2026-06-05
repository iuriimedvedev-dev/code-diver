from __future__ import annotations

from statistics import mean
from typing import Any

from ..explanation import ExplanationMetrics
from ..services.evaluation_statistics import EvaluationStatistics


class AnswerMetrics:
    BINARY_METRICS = {
        "file_hit",
        "candidate_file_hit",
        "context_file_hit",
        "citation_path_valid_rate",
        "citation_line_valid_rate",
    }

    def __init__(self):
        self.text_metrics = ExplanationMetrics()
        self.statistics = EvaluationStatistics()

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
        aggregate: dict[str, float] = {}
        for key in metric_keys:
            values = [float((row.get("metrics") or {}).get(key, 0.0)) for row in rows]
            aggregate[key] = mean(values)
            aggregate.update(
                self.statistics.summarize(
                    key,
                    values,
                    binary=self._is_binary_metric(key, values),
                )
            )
        return aggregate

    def _is_binary_metric(self, key: str, values: list[float]) -> bool:
        if not all(value in {0.0, 1.0} for value in values):
            return False
        return key in self.BINARY_METRICS or "_hit@" in key or key.endswith("_hit")
