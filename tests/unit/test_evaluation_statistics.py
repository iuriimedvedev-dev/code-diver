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


def test_evaluation_statistics_clamps_continuous_rate_ci_near_upper_bound() -> None:
    # Regression for a real report where `citation_path_valid_rate` sat at mean 0.998
    # with per-case values that are fractional (not strictly 0/1), so `binary=False`
    # normal interval overshot to 1.002. A rate metric can never legitimately exceed 1.0.
    metrics = EvaluationStatistics().summarize(
        "citation_path_valid_rate", [1.0, 1.0, 1.0, 1.0, 0.9], binary=False
    )

    assert metrics["citation_path_valid_rate_ci95_high"] <= 1.0
    assert metrics["citation_path_valid_rate_ci95_low"] >= 0.0


def test_evaluation_statistics_clamps_continuous_rate_ci_near_lower_bound() -> None:
    metrics = EvaluationStatistics().summarize(
        "citation_line_valid_rate", [0.0, 0.0, 0.0, 0.0, 0.05], binary=False
    )

    assert metrics["citation_line_valid_rate_ci95_low"] >= 0.0
    assert metrics["citation_line_valid_rate_ci95_high"] <= 1.0


def test_evaluation_statistics_leaves_judge_overall_ci_unclamped_above_one() -> None:
    # `judge_overall` lives on a 0-5 scale, not a [0, 1] rate. A high mean with low
    # variance should be allowed to keep a CI upper bound above 1.0.
    metrics = EvaluationStatistics().summarize("judge_overall", [4.3, 4.4, 4.2, 4.3, 4.4], binary=False)

    assert metrics["judge_overall_ci95_high"] > 1.0


def test_evaluation_statistics_ci95_width_matches_clamped_bounds() -> None:
    metrics = EvaluationStatistics().summarize(
        "citation_path_valid_rate", [1.0, 1.0, 1.0, 1.0, 0.9], binary=False
    )

    width = metrics["citation_path_valid_rate_ci95_high"] - metrics["citation_path_valid_rate_ci95_low"]
    assert metrics["citation_path_valid_rate_ci95_width"] == pytest.approx(width)
