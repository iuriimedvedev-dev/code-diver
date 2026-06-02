from __future__ import annotations

import pytest

from code_diver.services import EvaluationStatistics


pytestmark = pytest.mark.unit


def test_evaluation_statistics_reports_sample_variance_and_normal_ci() -> None:
    metrics = EvaluationStatistics().summarize("mrr@10", [0.0, 0.5, 1.0])

    assert metrics["mrr@10_variance"] == pytest.approx(0.25)
    assert metrics["mrr@10_stddev"] == pytest.approx(0.5)
    assert metrics["mrr@10_stderr"] == pytest.approx(0.288675, rel=1e-5)
    assert metrics["mrr@10_ci95_low"] < 0.5
    assert metrics["mrr@10_ci95_high"] > 0.5


def test_evaluation_statistics_reports_bounded_wilson_ci_for_binary_metrics() -> None:
    metrics = EvaluationStatistics().summarize("hit_rate@1", [1, 1, 0, 1], binary=True)

    assert metrics["hit_rate@1_variance"] == pytest.approx(0.25)
    assert 0.0 <= metrics["hit_rate@1_ci95_low"] <= 0.75
    assert 0.75 <= metrics["hit_rate@1_ci95_high"] <= 1.0
    assert metrics["hit_rate@1_ci95_width"] > 0
