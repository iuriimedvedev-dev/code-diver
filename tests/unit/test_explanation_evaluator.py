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

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str) -> GenerationResult:
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
                    "scores": {
                        "correctness": 5,
                        "completeness": 4,
                        "specificity": 4,
                        "groundedness": 5,
                    },
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
    assert report["metrics"]["judge_overall"] == 4.5
    assert report["usage"]["model_calls"] == 1
    assert report["judge_usage"]["model_calls"] == 1
    assert report["results"][0]["prediction"] == "Returns the sum of a and b."
