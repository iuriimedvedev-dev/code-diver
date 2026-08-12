"""Tests for `AnswerMetrics.aggregate()`'s handling of judge scores vs. judge failures.

`aggregate()` defaults a missing metric key to 0.0 for every metric family except the
LLM judge's score keys (`JUDGE_SCORE_METRICS`): a row whose judging FAILED (`judge_error`
set, no `judge_*` scores) must be excluded from the judge means rather than counted as a
worthless answer, since an infrastructure failure is a missing measurement, not a quality
one. Everything else keeps the original default-to-zero behaviour, since a key like
`file_hit` is legitimately absent on a case with no `expected_paths`.
"""

from __future__ import annotations

from typing import Any

import pytest

from code_diver.answering.answer_metrics import AnswerMetrics

pytestmark = pytest.mark.unit


def judged_row(case_id: str, overall: float) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "metrics": {
            "judge_overall": overall,
            "judge_answer_correctness": overall,
            "judge_abstained": 0.0,
            "judge_empty_answer": 0.0,
            "token_f1": 0.5,
        },
    }


def judge_error_row(case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "judge_error": "SchemaViolationError: missing criterion",
        "metrics": {"token_f1": 0.5},
    }


def test_judge_error_row_is_excluded_from_judge_overall_mean_not_counted_as_zero() -> None:
    rows = [judged_row("a", 4.0), judged_row("b", 4.0), judge_error_row("c")]

    aggregate = AnswerMetrics().aggregate(rows)

    # If the failed row were counted as a 0.0 (the old behaviour), the mean would be
    # (4.0 + 4.0 + 0.0) / 3 == 2.666...; excluding it correctly gives 4.0.
    assert aggregate["judge_overall"] == pytest.approx(4.0)


def test_judge_scored_count_reflects_only_rows_that_actually_contributed() -> None:
    rows = [judged_row("a", 4.0), judged_row("b", 3.0), judge_error_row("c")]

    aggregate = AnswerMetrics().aggregate(rows)

    assert aggregate["judge_scored_count"] == 2.0


def test_judge_scored_count_is_omitted_when_the_judge_never_ran() -> None:
    rows = [{"case_id": "a", "metrics": {"token_f1": 0.5}}]

    aggregate = AnswerMetrics().aggregate(rows)

    assert "judge_scored_count" not in aggregate
    assert "judge_overall" not in aggregate


def test_non_judge_metric_missing_on_some_rows_still_defaults_to_zero() -> None:
    """Regression guard: the present-only rule must be scoped to judge score keys only."""
    rows = [
        {"case_id": "a", "metrics": {"file_hit": 1.0}},
        {"case_id": "b", "metrics": {}},
    ]

    aggregate = AnswerMetrics().aggregate(rows)

    assert aggregate["file_hit"] == pytest.approx(0.5)


def test_judge_confidence_interval_is_computed_from_contributing_rows_only() -> None:
    rows = [judged_row("a", 4.0), judged_row("b", 4.0), judge_error_row("c")]

    aggregate = AnswerMetrics().aggregate(rows)

    # Two identical values with zero variance collapse the CI to a point at the mean --
    # a symptom that would not appear if the confidence interval were still (wrongly)
    # computed over all three rows including the excluded judge-error row.
    assert aggregate["judge_overall_ci95_low"] == pytest.approx(4.0)
    assert aggregate["judge_overall_ci95_high"] == pytest.approx(4.0)


def test_judge_duration_ms_keeps_default_to_zero_behaviour_despite_judge_prefix() -> None:
    """`judge_duration_ms` is a timing metric, not a judge score -- it must not be
    silently excluded from rows where it happens to be missing."""
    rows = [
        {"case_id": "a", "metrics": {"judge_duration_ms": 10.0}},
        {"case_id": "b", "metrics": {}},
    ]

    aggregate = AnswerMetrics().aggregate(rows)

    assert aggregate["judge_duration_ms"] == pytest.approx(5.0)
