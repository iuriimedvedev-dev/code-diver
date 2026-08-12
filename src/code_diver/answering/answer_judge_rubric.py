from __future__ import annotations

from typing import Any, ClassVar, Final

from ..generation.response_schemas import JUDGE_ANSWER_TYPES
from .answer_judge_criterion import AnswerJudgeCriterion

ANSWER_TYPE_SUBSTANTIVE: Final[str] = "substantive"
ANSWER_TYPE_ABSTENTION: Final[str] = "abstention"
ANSWER_TYPE_EMPTY: Final[str] = "empty"

# `hallucination_control` is deliberately excluded: an abstention that fabricates
# nothing should not be penalized on that axis, only on the axes that require a
# substantive claim to score well.
_CRITERIA_ZEROED_ON_ABSTENTION: Final[frozenset[str]] = frozenset(
    {
        "answer_correctness",
        "evidence_grounding",
        "coverage",
        "citation_quality",
        "specificity",
    }
)


class AnswerJudgeRubric:
    CRITERIA: ClassVar[list[AnswerJudgeCriterion]] = [
        AnswerJudgeCriterion("answer_correctness", "Answer correctness", 0.30),
        AnswerJudgeCriterion("evidence_grounding", "Evidence grounding", 0.20),
        AnswerJudgeCriterion("coverage", "Coverage of required facts", 0.15),
        AnswerJudgeCriterion("citation_quality", "File and line citation quality", 0.15),
        AnswerJudgeCriterion("specificity", "Code-specific detail", 0.10),
        AnswerJudgeCriterion("hallucination_control", "Hallucination control", 0.10),
    ]
    MAX_SCORE = 4.0

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        criteria_payload = self._criteria_payload(payload)
        answer_type = self._answer_type(payload)
        questionnaire: dict[str, dict[str, Any]] = {}
        flat_scores: dict[str, float] = {}
        weighted = 0.0
        total_weight = 0.0
        for criterion in self.CRITERIA:
            response = criteria_payload.get(criterion.id)
            if not isinstance(response, dict):
                response = {}
            raw_score = self._bounded_score(response.get("score"))
            enforced_score = self._enforce_answer_type(criterion.id, raw_score, answer_type)
            questionnaire[criterion.id] = {
                "label": criterion.label,
                "weight": criterion.weight,
                # The raw LLM score stays visible here even when `enforced_score`
                # overrides it below, so a reviewer can see what the model claimed.
                "score": raw_score,
                "answer": str(response.get("answer") or response.get("verdict") or "").strip(),
                "evidence": str(response.get("evidence") or response.get("reason") or "").strip(),
            }
            flat_scores[f"judge_{criterion.id}"] = enforced_score
            weighted += (enforced_score / self.MAX_SCORE) * criterion.weight
            total_weight += criterion.weight
        flat_scores["judge_overall"] = (weighted / total_weight * 5.0) if total_weight else 0.0
        flat_scores["judge_abstained"] = 1.0 if answer_type == ANSWER_TYPE_ABSTENTION else 0.0
        flat_scores["judge_empty_answer"] = 1.0 if answer_type == ANSWER_TYPE_EMPTY else 0.0
        flat_scores["judge_answer_type_missing"] = 1.0 if self._answer_type_missing(payload) else 0.0
        return {
            "scores": flat_scores,
            "questionnaire": questionnaire,
            "rationale": str(payload.get("rationale") or payload.get("summary") or "").strip(),
            "critical_issues": self._string_list(payload.get("critical_issues")),
        }

    def _answer_type(self, payload: dict[str, Any]) -> str:
        answer_type = payload.get("answer_type")
        if answer_type in JUDGE_ANSWER_TYPES:
            return str(answer_type)
        # Absent or unrecognized (e.g. older saved reports predate this field, or the
        # local judge model omitted it now that `JUDGE_SCHEMA` no longer requires it):
        # fall back to the pre-existing behavior of scoring the criteria as given.
        return ANSWER_TYPE_SUBSTANTIVE

    def _answer_type_missing(self, payload: dict[str, Any]) -> bool:
        """True when `answer_type` was absent, so it was defaulted to substantive.

        `answer_type` is no longer a required schema property (the local judge model
        frequently omits it), so this is read directly off the raw payload rather than
        re-derived from `_answer_type()`'s resolved value, which cannot distinguish an
        explicit `"substantive"` from a missing field.

        A high mean for this flag means `judge_abstained` is not trustworthy: every
        response with no `answer_type` was silently counted as substantive instead of
        actually being judged for abstention.
        """
        return payload.get("answer_type") is None

    def _enforce_answer_type(self, criterion_id: str, raw_score: float, answer_type: str) -> float:
        if answer_type == ANSWER_TYPE_EMPTY:
            return 0.0
        if answer_type == ANSWER_TYPE_ABSTENTION and criterion_id in _CRITERIA_ZEROED_ON_ABSTENTION:
            return 0.0
        return raw_score

    def _criteria_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        criteria = payload.get("criteria")
        if isinstance(criteria, dict):
            return criteria
        scores = payload.get("scores")
        if isinstance(scores, dict):
            return {key: {"score": value} for key, value in scores.items()}
        return {}

    def _bounded_score(self, value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(max(score, 0.0), self.MAX_SCORE)

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
