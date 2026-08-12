from __future__ import annotations

from typing import Any, ClassVar

from .explanation_judge_criterion import ExplanationJudgeCriterion


class ExplanationJudgeRubric:
    CRITERIA: ClassVar[list[ExplanationJudgeCriterion]] = [
        ExplanationJudgeCriterion("purpose_accuracy", "Purpose accuracy", 0.18),
        ExplanationJudgeCriterion("behavior_accuracy", "Behavior and control-flow accuracy", 0.22),
        ExplanationJudgeCriterion("api_contract", "Inputs, outputs, side effects, and errors", 0.15),
        ExplanationJudgeCriterion("groundedness", "Groundedness and hallucination control", 0.18),
        ExplanationJudgeCriterion("specificity", "Code-specific detail", 0.12),
        ExplanationJudgeCriterion("completeness", "Coverage of important behavior", 0.10),
        ExplanationJudgeCriterion("clarity", "Developer readability", 0.05),
    ]
    MAX_SCORE = 4.0

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        criteria_payload = self._criteria_payload(payload)
        questionnaire: dict[str, dict[str, Any]] = {}
        weighted = 0.0
        total_weight = 0.0
        flat_scores: dict[str, float] = {}
        for criterion in self.CRITERIA:
            response = criteria_payload.get(criterion.id)
            if isinstance(response, dict):
                score = self._bounded_score(response.get("score"))
                answer = str(response.get("answer") or response.get("verdict") or "").strip()
                evidence = str(response.get("evidence") or response.get("reason") or "").strip()
            else:
                score = self._bounded_score(response)
                answer = ""
                evidence = ""
            questionnaire[criterion.id] = {
                "label": criterion.label,
                "weight": criterion.weight,
                "score": score,
                "answer": answer,
                "evidence": evidence,
            }
            flat_scores[f"judge_{criterion.id}"] = score
            weighted += (score / self.MAX_SCORE) * criterion.weight
            total_weight += criterion.weight
        overall = (weighted / total_weight * 5.0) if total_weight else 0.0
        flat_scores["judge_overall"] = overall
        return {
            "scores": flat_scores,
            "questionnaire": questionnaire,
            "rationale": str(payload.get("rationale") or payload.get("summary") or "").strip(),
            "critical_issues": self._string_list(payload.get("critical_issues")),
        }

    def metric_keys(self) -> list[str]:
        return [f"judge_{criterion.id}" for criterion in self.CRITERIA] + ["judge_overall"]

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
