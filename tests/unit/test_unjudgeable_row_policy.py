from __future__ import annotations

from typing import Any

import pytest

from code_diver.answering.unjudgeable_row_policy import (
    REASON_EMPTY_PREDICTION,
    REASON_GENERATION_ERROR,
    is_judgeable,
    synthesize_judgment,
    unjudgeable_reason,
)
from code_diver.generation.response_schemas import JUDGE_CRITERIA_NAMES

pytestmark = pytest.mark.unit


def make_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"case_id": "case-0", "prediction": "a real answer"}
    row.update(overrides)
    return row


def test_row_with_nonempty_prediction_and_no_error_is_judgeable() -> None:
    row = make_row()
    assert is_judgeable(row)
    assert unjudgeable_reason(row) is None


def test_empty_prediction_is_unjudgeable_with_empty_prediction_reason() -> None:
    row = make_row(prediction="   ")
    assert not is_judgeable(row)
    assert unjudgeable_reason(row) == REASON_EMPTY_PREDICTION


def test_missing_prediction_key_is_unjudgeable() -> None:
    row = {"case_id": "case-0"}
    assert unjudgeable_reason(row) == REASON_EMPTY_PREDICTION


def test_errored_row_is_unjudgeable_with_generation_error_reason_even_with_a_prediction() -> None:
    row = make_row(error="generation failed: invalid json")
    assert not is_judgeable(row)
    assert unjudgeable_reason(row) == REASON_GENERATION_ERROR


def test_error_takes_precedence_over_empty_prediction_reason() -> None:
    row = make_row(prediction="", error="boom")
    assert unjudgeable_reason(row) == REASON_GENERATION_ERROR


def test_falsy_error_value_does_not_make_a_row_unjudgeable() -> None:
    row = make_row(error="")
    assert is_judgeable(row)


def test_synthesized_judgment_zeroes_every_canonical_criterion() -> None:
    judged = synthesize_judgment(REASON_EMPTY_PREDICTION)
    criterion_keys = {key for key in judged["scores"] if key.startswith("judge_")} - {
        "judge_overall",
        "judge_abstained",
        "judge_empty_answer",
    }
    assert criterion_keys == {f"judge_{name}" for name in JUDGE_CRITERIA_NAMES}
    for name in JUDGE_CRITERIA_NAMES:
        assert judged["scores"][f"judge_{name}"] == 0.0


def test_synthesized_judgment_sets_overall_zero_and_empty_answer_one() -> None:
    judged = synthesize_judgment(REASON_EMPTY_PREDICTION)
    assert judged["scores"]["judge_overall"] == 0.0
    assert judged["scores"]["judge_empty_answer"] == 1.0
    assert judged["scores"]["judge_abstained"] == 0.0


def test_synthesized_judgment_is_flagged_and_carries_its_reason() -> None:
    judged = synthesize_judgment(REASON_GENERATION_ERROR)
    assert judged["synthesized"] is True
    assert judged["reason"] == REASON_GENERATION_ERROR


def test_synthesized_judgment_reports_no_usage_and_no_model() -> None:
    judged = synthesize_judgment(REASON_EMPTY_PREDICTION)
    assert judged["usage"] is None
    assert judged["model"] is None
