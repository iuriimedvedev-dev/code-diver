"""`answer_type` is optional in `JUDGE_SCHEMA` now: the local 4B judge model frequently
omits it, and re-prompting on a missing-but-non-essential field burned every repair
attempt and lost the whole judgement. This module covers the two halves of that
decision: the payload still validates and scores sanely without it, and the resulting
silent coercion to `"substantive"` is observable via `judge_answer_type_missing`.
"""

from __future__ import annotations

import pytest

from code_diver.answering.answer_judge_payload_validator import (
    DEFAULT_ANSWER_TYPE,
    validate_judge_payload,
)
from code_diver.answering.answer_judge_rubric import AnswerJudgeRubric
from code_diver.answering.answer_metrics import AnswerMetrics
from code_diver.generation.response_schemas import JUDGE_ANSWER_TYPES, JUDGE_SCHEMA

pytestmark = pytest.mark.unit


def _all_four_criteria() -> dict[str, dict[str, int]]:
    return {
        "answer_correctness": {"score": 4},
        "evidence_grounding": {"score": 4},
        "coverage": {"score": 4},
        "citation_quality": {"score": 4},
        "specificity": {"score": 4},
        "hallucination_control": {"score": 4},
    }


def test_payload_without_answer_type_validates_and_scores_as_substantive() -> None:
    payload = {"criteria": _all_four_criteria()}

    resolved = validate_judge_payload(payload)

    assert resolved == DEFAULT_ANSWER_TYPE

    scored = AnswerJudgeRubric().score(payload)

    assert scored["scores"]["judge_overall"] == pytest.approx(5.0)
    assert scored["scores"]["judge_abstained"] == 0.0
    assert scored["scores"]["judge_empty_answer"] == 0.0
    assert scored["scores"]["judge_answer_type_missing"] == 1.0


def test_payload_with_explicit_substantive_is_not_flagged_as_missing() -> None:
    payload = {"answer_type": "substantive", "criteria": _all_four_criteria()}

    scored = AnswerJudgeRubric().score(payload)

    assert scored["scores"]["judge_answer_type_missing"] == 0.0


def test_abstention_still_clamps_and_is_not_flagged_as_missing() -> None:
    payload = {"answer_type": "abstention", "criteria": _all_four_criteria()}

    scored = AnswerJudgeRubric().score(payload)
    scores = scored["scores"]

    assert scores["judge_answer_correctness"] == 0.0
    assert scores["judge_evidence_grounding"] == 0.0
    assert scores["judge_coverage"] == 0.0
    assert scores["judge_citation_quality"] == 0.0
    assert scores["judge_specificity"] == 0.0
    assert scores["judge_hallucination_control"] == 4.0
    assert scores["judge_overall"] == pytest.approx(0.5)
    assert scores["judge_answer_type_missing"] == 0.0


def test_judge_schema_answer_type_is_optional_but_still_defined() -> None:
    assert "answer_type" not in JUDGE_SCHEMA["required"]

    answer_type_property = JUDGE_SCHEMA["properties"]["answer_type"]
    assert answer_type_property["type"] == "string"
    assert answer_type_property["enum"] == list(JUDGE_ANSWER_TYPES)
    assert len(answer_type_property["enum"]) == 3


def test_judge_answer_type_missing_is_a_registered_binary_metric() -> None:
    assert "judge_answer_type_missing" in AnswerMetrics.BINARY_METRICS
