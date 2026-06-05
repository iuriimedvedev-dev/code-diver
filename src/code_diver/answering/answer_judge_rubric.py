from __future__ import annotations

from typing import Any

from .answer_judge_criterion import AnswerJudgeCriterion


class AnswerJudgeRubric:
    CRITERIA = [
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
        questionnaire: dict[str, dict[str, Any]] = {}
        flat_scores: dict[str, float] = {}
        weighted = 0.0
        total_weight = 0.0
        for criterion in self.CRITERIA:
            response = criteria_payload.get(criterion.id)
            if not isinstance(response, dict):
                response = {}
            score = self._bounded_score(response.get("score"))
            questionnaire[criterion.id] = {
                "label": criterion.label,
                "weight": criterion.weight,
                "score": score,
                "answer": str(response.get("answer") or response.get("verdict") or "").strip(),
                "evidence": str(response.get("evidence") or response.get("reason") or "").strip(),
            }
            flat_scores[f"judge_{criterion.id}"] = score
            weighted += (score / self.MAX_SCORE) * criterion.weight
            total_weight += criterion.weight
        flat_scores["judge_overall"] = (weighted / total_weight * 5.0) if total_weight else 0.0
        return {
            "scores": flat_scores,
            "questionnaire": questionnaire,
            "rationale": str(payload.get("rationale") or payload.get("summary") or "").strip(),
            "critical_issues": self._string_list(payload.get("critical_issues")),
        }

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
