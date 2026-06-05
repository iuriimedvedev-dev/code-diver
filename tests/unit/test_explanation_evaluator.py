from __future__ import annotations

import json

import pytest

from code_diver.explanation import CodeExplanationEvaluator, ExplanationCase, ExplanationJudge, ExplanationMetrics
from code_diver.generation import GenerationResult


pytestmark = pytest.mark.unit


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str) -> GenerationResult:
        self.prompts.append(prompt)
        return GenerationResult(
            text=self.responses.pop(0),
            model=self.model,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )


def test_explanation_metrics_score_token_overlap() -> None:
    metrics = ExplanationMetrics().score("Converts XML into a URL list.", "Convert XML to URL List.")

    assert metrics["token_f1"] > 0.6
    assert metrics["key_token_recall"] > 0.6


def test_code_explanation_evaluator_generates_metrics_and_judge_scores() -> None:
    case = ExplanationCase(
        id="case",
        code="def add(a, b):\n    return a + b",
        reference="Return the sum of two values.",
        prompt="Explain it.",
    )
    prediction_provider = FakeProvider([json.dumps({"explanation": "Returns the sum of a and b."})])
    judge_provider = FakeProvider(
        [
            json.dumps(
                {
                    "criteria": {
                        "purpose_accuracy": {"score": 4, "answer": "yes", "evidence": "It returns a sum."},
                        "behavior_accuracy": {"score": 4, "answer": "yes", "evidence": "The return expression is a + b."},
                        "api_contract": {"score": 3, "answer": "mostly", "evidence": "Inputs and output are implied."},
                        "groundedness": {"score": 4, "answer": "yes", "evidence": "No unsupported claims."},
                        "specificity": {"score": 3, "answer": "mostly", "evidence": "Mentions sum and operands."},
                        "completeness": {"score": 3, "answer": "mostly", "evidence": "Simple function is covered."},
                        "clarity": {"score": 4, "answer": "yes", "evidence": "Readable."},
                    },
                    "critical_issues": [],
                    "rationale": "Grounded.",
                }
            )
        ]
    )

    report = CodeExplanationEvaluator(
        prediction_provider,
        judge=ExplanationJudge(judge_provider),
    ).evaluate([case])

    assert report["metrics"]["cases"] == 1.0
    assert report["metrics"]["token_f1"] > 0
    assert report["metrics"]["judge_overall"] == pytest.approx(4.5375)
    assert report["metrics"]["judge_behavior_accuracy"] == 4.0
    assert report["usage"]["model_calls"] == 1
    assert report["judge_usage"]["model_calls"] == 1
    assert report["results"][0]["prediction"] == "Returns the sum of a and b."
    assert report["results"][0]["judge"]["questionnaire"]["api_contract"]["answer"] == "mostly"


def test_explanation_judge_uses_custom_prompt_file(tmp_path) -> None:
    prompt = tmp_path / "judge.md"
    prompt.write_text(
        "custom judge prompt {{metadata_json}} {{code}} {{reference}} {{prediction}} {{user_prompt}}",
        encoding="utf-8",
    )
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "criteria": {
                        "purpose_accuracy": {"score": 4},
                        "behavior_accuracy": {"score": 4},
                        "api_contract": {"score": 4},
                        "groundedness": {"score": 4},
                        "specificity": {"score": 4},
                        "completeness": {"score": 4},
                        "clarity": {"score": 4},
                    }
                }
            )
        ]
    )
    case = ExplanationCase(
        id="case",
        code="def ok():\n    return True",
        reference="Return true.",
        prompt="Explain it.",
        metadata={"path": "sample.py"},
    )

    judged = ExplanationJudge(provider, prompt_path=prompt).judge(case, "Returns true.")

    assert judged["scores"]["judge_overall"] == 5.0
    assert "custom judge prompt" in provider.prompts[0]
    assert "sample.py" in provider.prompts[0]
    assert judged["prompt_path"] == str(prompt)
