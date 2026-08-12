from __future__ import annotations

import math
import re
from collections.abc import Iterable

# Matches proportion-style metric names such as `citation_path_valid_rate` or
# `hit_rate@5`: a per-case value that is itself a count-over-count ratio and is
# therefore mathematically bounded to [0, 1]. Deliberately name-pattern based (not a
# value-range heuristic) so the rule is an explicit, auditable opt-in rather than
# something that silently reclassifies a metric because its sampled values happen to
# fall inside [0, 1] this run. Everything else -- durations, raw counts, judge scores
# on a 0-4/0-5 scale, ... -- keeps its natural, unclamped normal interval.
_UNIT_RATE_METRIC_PATTERN = re.compile(r"_rate(?:@\d+)?$")


class EvaluationStatistics:
    def summarize(self, name: str, values: Iterable[float], *, binary: bool = False) -> dict[str, float]:
        materialized = [float(value) for value in values]
        count = len(materialized)
        if count == 0:
            return self._empty(name)
        mean = sum(materialized) / count
        variance = self._sample_variance(materialized, mean)
        stddev = math.sqrt(variance)
        stderr = stddev / math.sqrt(count) if count else 0.0
        if binary:
            ci_low, ci_high = self._wilson_interval(mean, count)
        else:
            ci_low, ci_high = self._normal_interval(mean, stderr)
            if self._is_unit_rate_metric(name):
                ci_low, ci_high = max(0.0, ci_low), min(1.0, ci_high)
        return {
            f"{name}_variance": variance,
            f"{name}_stddev": stddev,
            f"{name}_stderr": stderr,
            f"{name}_ci95_low": ci_low,
            f"{name}_ci95_high": ci_high,
            f"{name}_ci95_width": ci_high - ci_low,
        }

    def _is_unit_rate_metric(self, name: str) -> bool:
        return bool(_UNIT_RATE_METRIC_PATTERN.search(name))

    def _empty(self, name: str) -> dict[str, float]:
        return {
            f"{name}_variance": 0.0,
            f"{name}_stddev": 0.0,
            f"{name}_stderr": 0.0,
            f"{name}_ci95_low": 0.0,
            f"{name}_ci95_high": 0.0,
            f"{name}_ci95_width": 0.0,
        }

    def _sample_variance(self, values: list[float], mean: float) -> float:
        if len(values) <= 1:
            return 0.0
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    def _normal_interval(self, mean: float, stderr: float) -> tuple[float, float]:
        radius = 1.96 * stderr
        return mean - radius, mean + radius

    def _wilson_interval(self, proportion: float, count: int) -> tuple[float, float]:
        if count <= 0:
            return 0.0, 0.0
        z = 1.96
        denominator = 1.0 + z * z / count
        center = (proportion + z * z / (2 * count)) / denominator
        radius = (
            z
            * math.sqrt((proportion * (1.0 - proportion) + z * z / (4 * count)) / count)
            / denominator
        )
        return max(0.0, center - radius), min(1.0, center + radius)
