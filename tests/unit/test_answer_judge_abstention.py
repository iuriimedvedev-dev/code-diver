from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.answering import AnswerCase, AnswerJudge, AnswerJudgePayloadError, AnswerJudgeRubric
from code_diver.generation import GenerationResult

pytestmark = pytest.mark.unit


class FakeGenerationProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, *, schema: dict | None = None) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str, *, schema: dict | None = None) -> GenerationResult:
        self.prompts.append(prompt)
        return GenerationResult(
            text=self.responses.pop(0),
            model=self.model,
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
        )


def _all_four_criteria() -> dict[str, dict[str, int]]:
    return {
        "answer_correctness": {"score": 4},
        "evidence_grounding": {"score": 4},
        "coverage": {"score": 4},
        "citation_quality": {"score": 4},
        "specificity": {"score": 4},
        "hallucination_control": {"score": 4},
    }


def test_rubric_zeroes_all_but_hallucination_control_for_abstention() -> None:
    scored = AnswerJudgeRubric().score(
        {
            "answer_type": "abstention",
            "criteria": _all_four_criteria(),
        }
    )

    scores = scored["scores"]
    assert scores["judge_answer_correctness"] == 0.0
    assert scores["judge_evidence_grounding"] == 0.0
    assert scores["judge_coverage"] == 0.0
    assert scores["judge_citation_quality"] == 0.0
    assert scores["judge_specificity"] == 0.0
    assert scores["judge_hallucination_control"] == 4.0
    assert scores["judge_overall"] == pytest.approx(0.5)
    assert scores["judge_abstained"] == 1.0
    assert scores["judge_empty_answer"] == 0.0
    # The raw LLM score stays visible in the questionnaire even though it was
    # overridden in the flat scores above.
    assert scored["questionnaire"]["answer_correctness"]["score"] == 4.0


def test_rubric_zeroes_everything_including_hallucination_control_for_empty() -> None:
    scored = AnswerJudgeRubric().score(
        {
            "answer_type": "empty",
            "criteria": _all_four_criteria(),
        }
    )

    scores = scored["scores"]
    assert scores["judge_hallucination_control"] == 0.0
    assert scores["judge_overall"] == pytest.approx(0.0)
    assert scores["judge_abstained"] == 0.0
    assert scores["judge_empty_answer"] == 1.0


def test_rubric_substantive_all_fours_scores_five_regression() -> None:
    scored = AnswerJudgeRubric().score(
        {
            "answer_type": "substantive",
            "criteria": _all_four_criteria(),
        }
    )

    assert scored["scores"]["judge_overall"] == pytest.approx(5.0)
    assert scored["scores"]["judge_abstained"] == 0.0
    assert scored["scores"]["judge_empty_answer"] == 0.0


def test_rubric_missing_answer_type_behaves_as_substantive() -> None:
    scored = AnswerJudgeRubric().score({"criteria": _all_four_criteria()})

    assert scored["scores"]["judge_overall"] == pytest.approx(5.0)
    assert scored["scores"]["judge_abstained"] == 0.0
    assert scored["scores"]["judge_empty_answer"] == 0.0


def test_judge_abstained_and_empty_keys_are_binary() -> None:
    scored = AnswerJudgeRubric().score({"answer_type": "abstention", "criteria": _all_four_criteria()})

    assert scored["scores"]["judge_abstained"] in {0.0, 1.0}
    assert scored["scores"]["judge_empty_answer"] in {0.0, 1.0}


def test_answer_judge_raises_on_missing_criterion(tmp_path: Path) -> None:
    judge_prompt = tmp_path / "judge.md"
    judge_prompt.write_text(
        "{{question}} {{metadata_json}} {{context}} {{reference}} {{prediction}}",
        encoding="utf-8",
    )
    payload = _all_four_criteria()
    del payload["coverage"]
    provider = FakeGenerationProvider(
        [json.dumps({"criteria": payload, "answer_type": "substantive", "critical_issues": [], "rationale": "x"})]
    )
    judge = AnswerJudge(provider, prompt_path=judge_prompt)
    case = AnswerCase(id="c", question="q", reference="r")

    with pytest.raises(AnswerJudgePayloadError, match="coverage"):
        judge.judge(case, "prediction", "context")


def test_answer_judge_raises_on_out_of_range_score(tmp_path: Path) -> None:
    judge_prompt = tmp_path / "judge.md"
    judge_prompt.write_text(
        "{{question}} {{metadata_json}} {{context}} {{reference}} {{prediction}}",
        encoding="utf-8",
    )
    payload = _all_four_criteria()
    payload["specificity"] = {"score": 9}
    provider = FakeGenerationProvider(
        [json.dumps({"criteria": payload, "answer_type": "substantive", "critical_issues": [], "rationale": "x"})]
    )
    judge = AnswerJudge(provider, prompt_path=judge_prompt)
    case = AnswerCase(id="c", question="q", reference="r")

    with pytest.raises(AnswerJudgePayloadError, match="specificity"):
        judge.judge(case, "prediction", "context")


def test_answer_judge_accepts_payload_without_answer_type(tmp_path: Path) -> None:
    judge_prompt = tmp_path / "judge.md"
    judge_prompt.write_text(
        "{{question}} {{metadata_json}} {{context}} {{reference}} {{prediction}}",
        encoding="utf-8",
    )
    provider = FakeGenerationProvider(
        [json.dumps({"criteria": _all_four_criteria(), "critical_issues": [], "rationale": "x"})]
    )
    judge = AnswerJudge(provider, prompt_path=judge_prompt)
    case = AnswerCase(id="c", question="q", reference="r")

    result = judge.judge(case, "prediction", "context")

    assert result["scores"]["judge_overall"] == pytest.approx(5.0)
    assert result["scores"]["judge_abstained"] == 0.0
