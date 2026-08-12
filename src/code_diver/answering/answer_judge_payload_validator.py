"""Validates parsed judge JSON before it reaches `AnswerJudgeRubric.score()`.

`AnswerJudgeRubric._bounded_score()` clamps out-of-range values but defaults missing
or malformed scores to 0.0. That makes a judge response that is missing a criterion
indistinguishable from a genuine 0/4 verdict, which silently poisons aggregate means
across a benchmark run. This module fails loudly instead: a malformed payload raises
`AnswerJudgePayloadError` so callers can count it as a judge error rather than a score.
"""

from __future__ import annotations

from typing import Any, Final

from ..generation.response_schemas import JUDGE_ANSWER_TYPES, JUDGE_CRITERIA_NAMES

MIN_CRITERION_SCORE: Final[int] = 0
MAX_CRITERION_SCORE: Final[int] = 4
DEFAULT_ANSWER_TYPE: Final[str] = "substantive"


class AnswerJudgePayloadError(Exception):
    """Raised when a judge model's parsed JSON payload is missing or malformed.

    Carries the list of specific reasons so logs and `judge_error` fields name what
    was wrong instead of a generic parse failure.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__(f"Malformed judge payload: {'; '.join(reasons)}")


def validate_judge_payload(payload: dict[str, Any]) -> str:
    """Validate a parsed judge payload, returning its normalized `answer_type`.

    Requires `criteria` to be a mapping containing all six criterion names, each with
    an integer-coercible `score` in `[0, 4]`. `answer_type`, if present, must be one of
    `JUDGE_ANSWER_TYPES`; if absent, it defaults to `"substantive"` for backwards
    compatibility with judge payloads recorded before this field existed.

    Raises:
        AnswerJudgePayloadError: if `criteria` is missing/malformed or `answer_type`
            is present but not a recognized value.
    """
    reasons: list[str] = []
    criteria = payload.get("criteria")
    if not isinstance(criteria, dict):
        reasons.append("'criteria' is missing or not an object")
        criteria = {}
    for name in JUDGE_CRITERIA_NAMES:
        response = criteria.get(name)
        if not isinstance(response, dict):
            reasons.append(f"criterion '{name}' is missing or not an object")
            continue
        score = response.get("score")
        if not _is_valid_score(score):
            reasons.append(f"criterion '{name}' has an invalid score: {score!r}")

    raw_answer_type = payload.get("answer_type")
    answer_type = DEFAULT_ANSWER_TYPE if raw_answer_type is None else raw_answer_type
    if answer_type not in JUDGE_ANSWER_TYPES:
        reasons.append(f"'answer_type' has an invalid value: {answer_type!r}")

    if reasons:
        raise AnswerJudgePayloadError(reasons)
    return str(answer_type)


def _is_valid_score(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if value != int(value):
        return False
    return MIN_CRITERION_SCORE <= value <= MAX_CRITERION_SCORE
