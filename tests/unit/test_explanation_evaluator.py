from __future__ import annotations

import json
from threading import Lock
from time import sleep

import pytest

from code_diver.explanation import CodeExplanationEvaluator, ExplanationCase, ExplanationJudge, ExplanationMetrics
from code_diver.explanation.jsonish_parser import JsonishParser
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


class PromptAwareProvider:
    name = "prompt-aware"
    model = "prompt-aware-model"

    def __init__(self):
        self.prompts: list[str] = []
        self.lock = Lock()

    def generate_json_result(self, prompt: str) -> GenerationResult:
        with self.lock:
            self.prompts.append(prompt)
        if "slow" in prompt:
            sleep(0.02)
            explanation = "Slow case explained."
        else:
            explanation = "Fast case explained."
        return GenerationResult(
            text=json.dumps({"explanation": explanation}),
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


def test_code_explanation_evaluator_records_malformed_case_and_continues() -> None:
    cases = [
        ExplanationCase(id="bad", code="def bad(): pass", reference="Does bad.", prompt="Explain it."),
        ExplanationCase(id="good", code="def ok(): return True", reference="Return true.", prompt="Explain it."),
    ]
    provider = FakeProvider(
        [
            '{"explanation": "broken\njson"}',
            json.dumps({"explanation": "Returns true."}),
        ]
    )

    report = CodeExplanationEvaluator(provider).evaluate(cases)

    assert report["metrics"]["cases"] == 2.0
    assert report["error_count"] == 1
    assert report["results"][0]["prediction"] == ""
    assert "error" in report["results"][0]
    assert report["results"][1]["prediction"] == "Returns true."


def test_jsonish_parser_repairs_fenced_json_with_invalid_escapes() -> None:
    parsed = JsonishParser().parse_object(
        '```json\n{"explanation": "Uses regex \\(group\\) and path C:\\\\tmp."}\n```'
    )

    assert parsed["explanation"] == "Uses regex \\(group\\) and path C:\\tmp."


def test_code_explanation_evaluator_can_run_cases_concurrently_in_dataset_order() -> None:
    cases = [
        ExplanationCase(id="slow", code="def slow(): pass", reference="Slow case.", prompt="Explain slow."),
        ExplanationCase(id="fast", code="def fast(): pass", reference="Fast case.", prompt="Explain fast."),
    ]
    progress: list[int] = []

    report = CodeExplanationEvaluator(
        PromptAwareProvider(),
        workers=2,
        progress_callback=lambda completed, _total, _case: progress.append(completed),
    ).evaluate(cases)

    assert report["metrics"]["cases"] == 2.0
    assert [row["case_id"] for row in report["results"]] == ["slow", "fast"]
    assert [row["prediction"] for row in report["results"]] == ["Slow case explained.", "Fast case explained."]
    assert sorted(progress) == [1, 2]
    assert report["usage"]["model_calls"] == 2
