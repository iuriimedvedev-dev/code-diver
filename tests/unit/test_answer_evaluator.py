from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.answering import (
    AnswerCase,
    AnswerContextBuilder,
    AnswerDatasetLoader,
    AnswerEvaluator,
    AnswerJudge,
    AnswerJudgeRubric,
)
from code_diver.domain import CodeItem, SearchResult
from code_diver.generation import GenerationResult


pytestmark = pytest.mark.unit


class FakeGenerationProvider:
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
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
        )


class FakeRetrievalStrategy:
    def __init__(self, results: list[SearchResult]):
        self.results = results
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.queries.append((query, limit))
        return self.results[:limit]


def test_answer_case_extracts_paths_from_reference() -> None:
    case = AnswerCase.from_json(
        {
            "id": "case",
            "question": "Where is auth handled?",
            "answer": "See src/auth/service.py: line 10-30 and src/http/routes.py: line 4.",
            "repo": "owner/repo",
        }
    )

    assert case.expected_paths == ["src/auth/service.py", "src/http/routes.py"]
    assert case.metadata["repo"] == "owner/repo"


def test_answer_dataset_loader_reports_bad_rows(tmp_path: Path) -> None:
    dataset = tmp_path / "answers.jsonl"
    dataset.write_text('{"id":"bad","question":"missing reference"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid answer dataset row 1"):
        AnswerDatasetLoader().load(dataset)


def test_answer_context_builder_reads_ranked_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login():\n    return True\n", encoding="utf-8")
    results = [
        SearchResult(
            CodeItem(
                id="src/auth.py",
                path="src/auth.py",
                title="auth",
                content="Authentication summary.",
                start_line=1,
            ),
            0.9,
        )
    ]

    context = AnswerContextBuilder(tmp_path, max_files=1, lines_per_file=40).build(results)

    assert context.files == ["src/auth.py"]
    assert context.file_ranges["src/auth.py"] == (1, 2)
    assert "Authentication summary" in context.text
    assert "def login" in context.text
    assert "src/auth.py:1-2" in context.text


def test_answer_evaluator_searches_reads_answers_and_judges(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login(user):\n    return user.token is not None\n", encoding="utf-8")
    retrieval = FakeRetrievalStrategy(
        [
            SearchResult(
                CodeItem(
                    id="src/auth.py",
                    path="src/auth.py",
                    title="auth",
                    content="Checks whether a user has a token.",
                    start_line=1,
                ),
                0.91,
            )
        ]
    )
    answer_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "answer": "Authentication is checked in src/auth.py:1-2 by login, which requires a token.",
                    "citations": [{"path": "src/auth.py", "lines": "1-2", "reason": "token check"}],
                    "confidence": 0.9,
                }
            )
        ]
    )
    judge_prompt = tmp_path / "judge.md"
    judge_prompt.write_text(
        "{{question}} {{metadata_json}} {{context}} {{reference}} {{prediction}}",
        encoding="utf-8",
    )
    judge_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "criteria": {
                        "answer_correctness": {"score": 4},
                        "evidence_grounding": {"score": 4},
                        "coverage": {"score": 3},
                        "citation_quality": {"score": 4},
                        "specificity": {"score": 4},
                        "hallucination_control": {"score": 4},
                    },
                    "critical_issues": [],
                    "rationale": "Grounded.",
                }
            )
        ]
    )
    case = AnswerCase(
        id="auth",
        question="Where is authentication checked?",
        reference="src/auth.py: line 1-2 checks user tokens.",
        expected_paths=["src/auth.py"],
    )

    report = AnswerEvaluator(
        retrieval,
        answer_provider,
        AnswerContextBuilder(tmp_path, max_files=1, lines_per_file=40),
        judge=AnswerJudge(judge_provider, prompt_path=judge_prompt),
        limit=5,
    ).evaluate([case])

    assert retrieval.queries == [("Where is authentication checked?", 5)]
    assert report["metrics"]["cases"] == 1.0
    assert report["metrics"]["file_hit"] == 1.0
    assert report["metrics"]["file_recall"] == 1.0
    assert report["metrics"]["candidate_file_hit@1"] == 1.0
    assert report["metrics"]["candidate_file_recall@5"] == 1.0
    assert report["metrics"]["context_file_hit"] == 1.0
    assert report["metrics"]["context_file_recall"] == 1.0
    assert report["metrics"]["retrieval_duration_ms"] >= 0
    assert report["metrics"]["context_duration_ms"] >= 0
    assert report["metrics"]["generation_duration_ms"] >= 0
    assert report["metrics"]["judge_duration_ms"] >= 0
    assert report["metrics"]["citation_count"] == 1.0
    assert report["metrics"]["citation_path_valid_rate"] == 1.0
    assert report["metrics"]["citation_line_valid_rate"] == 1.0
    assert report["metrics"]["judge_overall"] > 4.0
    assert report["usage"]["model_calls"] == 1
    assert report["judge_usage"]["model_calls"] == 1
    assert report["results"][0]["context_files"] == ["src/auth.py"]


def test_answer_judge_rubric_computes_weighted_overall() -> None:
    scored = AnswerJudgeRubric().score(
        {
            "criteria": {
                "answer_correctness": {"score": 4},
                "evidence_grounding": {"score": 4},
                "coverage": {"score": 4},
                "citation_quality": {"score": 4},
                "specificity": {"score": 4},
                "hallucination_control": {"score": 4},
            }
        }
    )

    assert scored["scores"]["judge_overall"] == pytest.approx(5.0)
