from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.answering import (
    AnswerCandidateReranker,
    AnswerCase,
    AnswerContextBuilder,
    AnswerDatasetLoader,
    AnswerEvaluator,
    AnswerJudge,
    AnswerJudgeRubric,
    AnswerQueryPlanner,
)
from code_diver.config import LlmRerankConfig
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
    def __init__(self, results: list[SearchResult] | dict[str, list[SearchResult]]):
        self.results = results
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[SearchResult]:
        self.queries.append((query, limit))
        if isinstance(self.results, dict):
            return self.results.get(query, [])[:limit]
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
    assert report["metrics"]["file_recall_variance"] == 0.0
    assert report["metrics"]["file_hit_ci95_low"] >= 0.0
    assert report["metrics"]["file_hit_ci95_high"] <= 1.0
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


def test_answer_evaluator_preserves_retrieval_metrics_when_answer_json_breaks(tmp_path: Path) -> None:
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
    answer_provider = FakeGenerationProvider(['{"answer":"unterminated"'])
    case = AnswerCase(
        id="auth",
        question="Where is authentication checked?",
        reference="src/auth.py checks user tokens.",
        expected_paths=["src/auth.py"],
    )

    report = AnswerEvaluator(
        retrieval,
        answer_provider,
        AnswerContextBuilder(tmp_path, max_files=1, lines_per_file=40),
        limit=5,
    ).evaluate([case])

    assert report["error_count"] == 1
    assert report["metrics"]["file_hit"] == 1.0
    assert report["metrics"]["file_recall"] == 1.0
    assert report["metrics"]["context_file_recall"] == 1.0
    assert report["results"][0]["retrieved_files"] == ["src/auth.py"]
    assert report["results"][0]["context_files"] == ["src/auth.py"]
    assert "error" in report["results"][0]


def test_answer_evaluator_uses_llm_generated_search_queries(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "state.py").write_text("def probabilities(state):\n    return state\n", encoding="utf-8")
    (src / "backend.py").write_text("def sample_frequencies(probabilities):\n    return probabilities\n", encoding="utf-8")
    state_result = SearchResult(
        CodeItem(
            id="src/state.py",
            path="src/state.py",
            title="state",
            content="Calculates probabilities from quantum states.",
            start_line=1,
        ),
        0.7,
    )
    backend_result = SearchResult(
        CodeItem(
            id="src/backend.py",
            path="src/backend.py",
            title="backend",
            content="Samples final measurement frequencies from probabilities.",
            start_line=1,
        ),
        0.8,
    )
    retrieval = FakeRetrievalStrategy(
        {
            "Where does measurement data flow to final outcomes?": [],
            "measurement probability flow": [state_result],
            "backend sampling frequencies": [backend_result],
        }
    )
    planner_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "queries": [
                        {"query": "measurement probability flow"},
                        {"query": "backend sampling frequencies"},
                    ],
                    "rationale": "Split state probabilities from backend sampling.",
                }
            )
        ]
    )
    answer_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "answer": "Measurement data flows through state probabilities and backend sampling.",
                    "citations": [
                        {"path": "src/state.py", "lines": "1", "reason": "probabilities"},
                        {"path": "src/backend.py", "lines": "1", "reason": "sampling"},
                    ],
                }
            )
        ]
    )
    case = AnswerCase(
        id="measurement",
        question="Where does measurement data flow to final outcomes?",
        reference="src/state.py computes probabilities and src/backend.py samples frequencies.",
        expected_paths=["src/state.py", "src/backend.py"],
    )

    report = AnswerEvaluator(
        retrieval,
        answer_provider,
        AnswerContextBuilder(tmp_path, max_files=4, lines_per_file=40),
        query_planner=AnswerQueryPlanner(planner_provider, max_queries=3),
        limit=4,
        query_workers=2,
    ).evaluate([case])

    assert sorted(query for query, _limit in retrieval.queries) == [
        "Where does measurement data flow to final outcomes?",
        "backend sampling frequencies",
        "measurement probability flow",
    ]
    assert report["planning_usage"]["model_calls"] == 1
    assert report["metrics"]["planned_query_count"] == 3.0
    assert report["metrics"]["file_recall"] == 1.0
    assert report["metrics"]["context_file_recall"] == 1.0
    assert report["results"][0]["query_plan"]["mode"] == "llm_multi_query"
    assert report["results"][0]["query_plan"]["queries"] == [
        "Where does measurement data flow to final outcomes?",
        "measurement probability flow",
        "backend sampling frequencies",
    ]


def test_answer_query_planner_includes_repository_context() -> None:
    planner_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "queries": [{"query": "auth route token validation"}],
                    "rationale": "Use repo layout.",
                }
            )
        ]
    )
    case = AnswerCase(
        id="auth",
        question="Where is auth?",
        reference="src/auth.py handles auth.",
        expected_paths=["src/auth.py"],
    )

    AnswerQueryPlanner(
        planner_provider,
        repository_context="# Repository Context\n- src/api routes live here",
    ).plan_result(case)

    assert "Repository orientation" in planner_provider.prompts[0]
    assert "src/api routes live here" in planner_provider.prompts[0]


def test_answer_evaluator_includes_repository_context_in_answer_prompt(tmp_path: Path) -> None:
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
                    "answer": "Authentication is checked in src/auth.py.",
                    "citations": [{"path": "src/auth.py", "lines": "1-2", "reason": "token check"}],
                }
            )
        ]
    )

    AnswerEvaluator(
        retrieval,
        answer_provider,
        AnswerContextBuilder(tmp_path, max_files=1, lines_per_file=40),
        repository_context="# Repository Context\n- src contains app code",
        limit=5,
    ).evaluate(
        [
            AnswerCase(
                id="auth",
                question="Where is authentication checked?",
                reference="src/auth.py checks user tokens.",
                expected_paths=["src/auth.py"],
            )
        ]
    )

    assert "Repository orientation" in answer_provider.prompts[0]
    assert "src contains app code" in answer_provider.prompts[0]


def test_answer_evaluator_can_rerank_merged_planned_query_pool(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.py").write_text("def alpha_owner():\n    return 'broad'\n", encoding="utf-8")
    (src / "beta.py").write_text("def beta_owner():\n    return 'specific'\n", encoding="utf-8")
    alpha = SearchResult(
        CodeItem(
            id="src/alpha.py",
            path="src/alpha.py",
            title="alpha",
            content="Broad candidate.",
            start_line=1,
        ),
        0.9,
    )
    beta = SearchResult(
        CodeItem(
            id="src/beta.py",
            path="src/beta.py",
            title="beta",
            content="Specific candidate.",
            start_line=1,
        ),
        0.1,
    )
    main_retrieval = FakeRetrievalStrategy([])
    probe_retrieval = FakeRetrievalStrategy(
        {
            "Where is the exact owner?": [],
            "broad owner": [alpha],
            "specific owner": [beta],
        }
    )
    planner_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "queries": [{"query": "broad owner"}, {"query": "specific owner"}],
                    "rationale": "Try broad and specific probes.",
                }
            )
        ]
    )
    rerank_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "results": [
                        {"index": 2, "confidence": 0.9},
                        {"index": 1, "confidence": 0.4},
                    ]
                }
            )
        ]
    )
    answer_provider = FakeGenerationProvider(
        [
            json.dumps(
                {
                    "answer": "The exact owner is beta.",
                    "citations": [{"path": "src/beta.py", "lines": "1", "reason": "specific owner"}],
                }
            )
        ]
    )

    report = AnswerEvaluator(
        main_retrieval,
        answer_provider,
        AnswerContextBuilder(tmp_path, max_files=2, lines_per_file=40),
        query_planner=AnswerQueryPlanner(planner_provider, max_queries=3),
        query_retrieval_strategy=probe_retrieval,
        query_result_reranker=AnswerCandidateReranker(
            rerank_provider,
            LlmRerankConfig(candidate_limit=10, rerank_limit=2, retry_attempts=1),
        ),
        limit=2,
        query_workers=2,
    ).evaluate(
        [
            AnswerCase(
                id="owner",
                question="Where is the exact owner?",
                reference="src/beta.py owns the specific behavior.",
                expected_paths=["src/beta.py"],
            )
        ]
    )

    assert main_retrieval.queries == []
    assert sorted(query for query, _limit in probe_retrieval.queries) == [
        "Where is the exact owner?",
        "broad owner",
        "specific owner",
    ]
    assert report["results"][0]["retrieved_files"][0] == "src/beta.py"
    assert report["results"][0]["query_plan"]["final_rerank"]["selected_indices"] == [2, 1]
    assert report["results"][0]["query_plan"]["final_rerank"]["selected_candidates"][0]["path"] == "src/beta.py"
    assert report["results"][0]["query_plan"]["final_rerank"]["selected_candidates"][0]["confidence"] == 0.9
    assert report["rerank_usage"]["model_calls"] == 1
    assert report["metrics"]["file_mrr"] == 1.0


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
