"""Shared policy for answer-eval report rows that must not reach the LLM judge.

Two call sites attach judge scores to a report row after the fact:
`scripts/rejudge_answer_report.py` (posthoc rejudging of an existing report) and
`AnswerReportJudge._judge_row()` (the live `judge` CLI subcommand). Before this module
existed they disagreed on what to do with a row whose generation step already failed --
an empty/whitespace prediction, or a row carrying a truthy `error` key:

- The rejudge script skipped the judge call entirely and returned the row with no
  `judge_*` keys at all.
- `AnswerReportJudge._judge_row()` had no such guard and called the judge model anyway,
  asking it to grade nothing.

Both are wrong, and in different directions. Never calling the judge is right --
grading an empty string wastes a model call and its "score" is meaningless -- but
silently omitting `judge_*` keys is not: `AnswerMetrics.aggregate()` only ever averages
keys that are present on a row (see `answer_metrics.py`), so a skipped row vanishes from
the judge means instead of counting as the worst outcome. That inflates every judge
metric by excluding exactly the cases most likely to be bad.

This module is the single place that decides both questions -- is a row judgeable, and
if not, what scores does it get -- so every caller applies the same rule.
"""

from __future__ import annotations

from typing import Any, Final

from ..generation.response_schemas import JUDGE_CRITERIA_NAMES

# Why a row was routed away from the LLM judge. Stored verbatim in the synthesized
# judge block's `reason` field so a report reader can tell the two cases apart.
REASON_EMPTY_PREDICTION: Final[str] = "empty_prediction"
REASON_GENERATION_ERROR: Final[str] = "generation_error"

_ZERO_SCORE: Final[float] = 0.0
_SYNTHESIZED_EMPTY_ANSWER_SCORE: Final[float] = 1.0
_SYNTHESIZED_ABSTAINED_SCORE: Final[float] = 0.0


def unjudgeable_reason(row: dict[str, Any]) -> str | None:
    """Return why `row` cannot be sent to the LLM judge, or `None` if it can.

    A row is unjudgeable when it already carries a truthy `error` key from a failed
    generation step, or when its `prediction` is empty or whitespace-only. `error` is
    checked first: `AnswerEvaluator._evaluate_case()` writes `prediction=""` alongside
    `error` on a parse failure, and the error is the more specific reason.
    """
    if row.get("error"):
        return REASON_GENERATION_ERROR
    prediction = str(row.get("prediction") or "").strip()
    if not prediction:
        return REASON_EMPTY_PREDICTION
    return None


def is_judgeable(row: dict[str, Any]) -> bool:
    """True if `row` should be sent to the LLM judge."""
    return unjudgeable_reason(row) is None


def synthesize_judgment(reason: str) -> dict[str, Any]:
    """Build a judge-shaped result for an unjudgeable row without calling the judge model.

    Every criterion scores 0.0, `judge_overall` is 0.0, `judge_empty_answer` is 1.0, and
    `judge_abstained` is 0.0: the row asserted nothing, so it is scored as the worst
    outcome rather than dropped from the aggregate. The returned dict mirrors the shape
    `AnswerJudge.judge()` returns (`scores`, `usage`, `model`, ...) so both call sites can
    merge it identically, but is marked `synthesized` so it can never be mistaken for an
    actual model judgement, and `usage` is `None` so no token/model-call accounting is
    recorded for a call that never happened.
    """
    scores: dict[str, float] = {f"judge_{name}": _ZERO_SCORE for name in JUDGE_CRITERIA_NAMES}
    scores["judge_overall"] = _ZERO_SCORE
    scores["judge_abstained"] = _SYNTHESIZED_ABSTAINED_SCORE
    scores["judge_empty_answer"] = _SYNTHESIZED_EMPTY_ANSWER_SCORE
    return {
        "scores": scores,
        "questionnaire": {},
        "rationale": "",
        "critical_issues": [],
        "model": None,
        "usage": None,
        "synthesized": True,
        "reason": reason,
    }
