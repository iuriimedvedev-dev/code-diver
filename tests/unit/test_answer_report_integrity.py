"""Regression tests for the report row-count integrity guard.

A 100-case judged report (and its `.partial.json` recovery sibling) was silently overwritten
by an unrelated 10-case run. This guard makes that class of truncation fail loudly instead of
silently, at every place an answer-evaluation report's `metrics` block is assembled:
`AnswerEvaluator.evaluate()`, `AnswerReportJudge.judge_payload()`, and
`scripts/rejudge_answer_report.py`'s hand-rolled equivalent.

Under the current implementation of all three, every per-row worker already catches its own
exceptions and always contributes a placeholder row, so a genuine row-count mismatch cannot
occur through the public API today -- that is the whole point of the guard: it exists to
catch a *future* regression, not a currently reachable bug. The "triggers failure" tests
below therefore monkeypatch each integration point's row-producing method to simulate exactly
such a regression (a dropped row), pinning that the guard actually fires when it happens,
while the "complete" tests exercise the real, unmodified code path to pin that nothing fires
(and the count fields land in the payload) when nothing is wrong.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from code_diver.answering import AnswerReportJudge
from code_diver.answering.answer_case import AnswerCase
from code_diver.answering.answer_context_builder import AnswerContextBuilder
from code_diver.answering.answer_evaluator import AnswerEvaluator
from code_diver.answering.answer_report_integrity import (
    IncompleteAnswerReportError,
    assert_case_count_matches,
    stamp_case_counts,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REJUDGE = load_script("rejudge_answer_report")


# --- Pure shared-module behaviour -------------------------------------------------------


def test_stamp_case_counts_records_requested_count_as_float() -> None:
    metrics: dict[str, Any] = {"cases": 3.0}

    stamp_case_counts(metrics, case_count_requested=3, row_count=3)

    assert metrics["case_count_requested"] == 3.0
    assert isinstance(metrics["case_count_requested"], float)


def test_assert_case_count_matches_passes_when_equal() -> None:
    assert_case_count_matches(case_count_requested=10, row_count=10, context="test")


def test_assert_case_count_matches_raises_when_short() -> None:
    with pytest.raises(IncompleteAnswerReportError, match=r"10.*100|100.*10"):
        assert_case_count_matches(case_count_requested=100, row_count=10, context="test")


def test_incomplete_answer_report_error_carries_both_counts() -> None:
    with pytest.raises(IncompleteAnswerReportError) as excinfo:
        assert_case_count_matches(case_count_requested=100, row_count=10)

    assert excinfo.value.case_count_requested == 100
    assert excinfo.value.row_count == 10


# --- AnswerEvaluator.evaluate() wiring --------------------------------------------------


class _FakeRetrievalStrategy:
    def search(self, query: str, limit: int) -> list[Any]:
        return []


class _FakeAnswerProvider:
    model = "fake-model"


def _make_case(case_id: str) -> AnswerCase:
    return AnswerCase(id=case_id, question=f"question {case_id}", reference=f"reference {case_id}")


def _dropped_row_evaluate_case(self: AnswerEvaluator, case: AnswerCase) -> dict[str, Any]:
    """Stands in for a hypothetical regression where a row silently goes missing."""
    return {
        "row": None,
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "generation_model": "fake-model",
        "planning_usage": None,
        "planning_model": None,
        "rerank_usage": None,
        "rerank_model": None,
        "judge_usage": None,
        "judge_model": None,
        "error": 0,
        "judge_error": 0,
    }


def test_answer_evaluator_raises_when_a_row_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AnswerEvaluator, "_evaluate_case", _dropped_row_evaluate_case)
    evaluator = AnswerEvaluator(
        _FakeRetrievalStrategy(),
        _FakeAnswerProvider(),
        AnswerContextBuilder(tmp_path),
    )

    with pytest.raises(IncompleteAnswerReportError) as excinfo:
        evaluator.evaluate([_make_case("case-1")])

    assert excinfo.value.case_count_requested == 1
    assert excinfo.value.row_count == 0


def _stub_evaluate_case(self: AnswerEvaluator, case: AnswerCase) -> dict[str, Any]:
    return {
        "row": {"case_id": case.id, "metrics": {}},
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "generation_model": "fake-model",
        "planning_usage": None,
        "planning_model": None,
        "rerank_usage": None,
        "rerank_model": None,
        "judge_usage": None,
        "judge_model": None,
        "error": 0,
        "judge_error": 0,
    }


def test_answer_evaluator_complete_run_stamps_matching_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AnswerEvaluator, "_evaluate_case", _stub_evaluate_case)
    evaluator = AnswerEvaluator(
        _FakeRetrievalStrategy(),
        _FakeAnswerProvider(),
        AnswerContextBuilder(tmp_path),
    )

    report = evaluator.evaluate([_make_case("case-1"), _make_case("case-2")])

    assert report["metrics"]["cases"] == 2.0
    assert report["metrics"]["case_count_requested"] == 2.0


# --- AnswerReportJudge.judge_payload() wiring -------------------------------------------


class _StubJudge:
    class _StubProvider:
        model = "stub-judge-model"

    DEFAULT_PROMPT_PATH = Path("prompts/code-answer-judge.md")

    def __init__(self) -> None:
        self.prompt_path = self.DEFAULT_PROMPT_PATH
        self.provider = self._StubProvider()

    def judge(self, case: Any, prediction: str, context: str) -> dict[str, Any]:
        raise AssertionError("judge() should not be called by these tests")


def test_answer_report_judge_raises_when_a_row_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    def _dropped_row_judge_row(self: AnswerReportJudge, row: dict[str, Any]) -> dict[str, Any]:
        return {"row": None, "usage": None, "model": None, "error": 0}

    monkeypatch.setattr(AnswerReportJudge, "_judge_row", _dropped_row_judge_row)
    payload = {"results": [{"case_id": "case-1", "metrics": {}}]}

    with pytest.raises(IncompleteAnswerReportError) as excinfo:
        AnswerReportJudge(judge=_StubJudge()).judge_payload(payload)

    assert excinfo.value.case_count_requested == 1
    assert excinfo.value.row_count == 0


def test_answer_report_judge_complete_run_stamps_matching_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    def _stub_judge_row(self: AnswerReportJudge, row: dict[str, Any]) -> dict[str, Any]:
        return {"row": dict(row), "usage": None, "model": None, "error": 0}

    monkeypatch.setattr(AnswerReportJudge, "_judge_row", _stub_judge_row)
    payload = {
        "results": [
            {"case_id": "case-1", "metrics": {}},
            {"case_id": "case-2", "metrics": {}},
        ]
    }

    judged = AnswerReportJudge(judge=_StubJudge()).judge_payload(payload)

    assert judged["metrics"]["cases"] == 2.0
    assert judged["metrics"]["case_count_requested"] == 2.0


# --- scripts/rejudge_answer_report.py wiring --------------------------------------------


def test_rejudge_script_stamps_matching_counts_on_a_complete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = {
        "results": [
            {
                "case_id": "case-1",
                "question": "q1",
                "reference": "r1",
                "prediction": "",
                "error": "generation failed: forced for this test",
                "metadata": {},
                "expected_paths": [],
                "metrics": {},
            }
        ]
    }
    input_path = tmp_path / "source.json"
    input_path.write_text(json.dumps(source), encoding="utf-8")
    output_path = tmp_path / "rejudged.json"

    monkeypatch.setattr(REJUDGE, "AnswerJudge", lambda *a, **k: _StubJudge())
    monkeypatch.setattr(REJUDGE, "create_generation_provider", lambda config: object())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rejudge_answer_report.py",
            str(input_path),
            "--judge-config",
            str(tmp_path / "missing-config.yml"),
            "--judge-prompt",
            str(tmp_path / "missing-prompt.md"),
            "--output",
            str(output_path),
        ],
    )

    exit_code = REJUDGE.main()

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["metrics"]["cases"] == 1.0
    assert payload["metrics"]["case_count_requested"] == 1.0
