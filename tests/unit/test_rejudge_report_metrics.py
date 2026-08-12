"""Regression tests for the metrics defect in `scripts/rejudge_answer_report.py`.

Before the fix, the script hand-rolled a mean over only `judge_*` keys, discarding every
deterministic per-row metric (`answer_grounded`, `context_bundle_complete`,
`candidate_file_hit`, `token_f1`, ...) and every confidence-interval suffix. These tests
pin the fixed behaviour: the script must aggregate the FULL merged row set through
`AnswerMetrics().aggregate()`, the same call `AnswerReportJudge.judge_payload()` makes, so
a rejudged report is self-contained and carries statistical error bars on `judge_overall`.

`test_rejudge_script_and_answer_report_judge_agree_on_generation_error_rows` below covers
a second, previously-fixed divergence: on a row where generation already failed (empty
prediction, top-level `error` set), the script used to skip judging silently (no `judge_*`
keys at all) while `AnswerReportJudge` called the judge model anyway. Both paths now route
such rows through `code_diver.answering.unjudgeable_row_policy`, which synthesizes zeroed
scores instead of calling the judge, so the two paths agree.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from code_diver.answering.answer_report_judge import AnswerReportJudge

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# Deterministic per-row metrics that a rejudged report must not drop from its top-level
# aggregate. These are the four the defect report calls out by name.
DETERMINISTIC_METRICS: tuple[str, ...] = (
    "context_bundle_complete",
    "answer_grounded",
    "candidate_file_hit",
    "token_f1",
)

# Canned `judge_overall` per case_id -- fixed so the same synthetic input produces the
# same judged output regardless of which code path (script vs. AnswerReportJudge) runs it.
# "case-err" is present only so the mapping shape matches `make_error_row()`'s case_id;
# neither path is expected to call `StubJudge.judge()` for it at all, since both now route
# it through `unjudgeable_row_policy` instead.
CASE_OVERALL: dict[str, float] = {
    "case-0": 4.0,
    "case-1": 2.0,
    "case-2": 3.0,
    "case-err": 1.0,
}

JUDGE_CRITERIA: tuple[str, ...] = (
    "answer_correctness",
    "evidence_grounding",
    "coverage",
    "citation_quality",
    "specificity",
    "hallucination_control",
)

# Keys that are *expected* to diverge between the two code paths and are therefore
# excluded from the parity comparison, rather than silently glossed over:
#   - "duration_ms": a script-only wall-clock bookkeeping key, unrelated to judging.
#   - "judge_duration_ms*": AnswerReportJudge._judge_row() stamps a per-row judge
#     duration into `row["metrics"]` on every successful judge call; the rejudge
#     script's `process()` never does. That is a real, pre-existing behavioural gap
#     between the two paths (not introduced by this fix) -- see the task report.
_KNOWN_DIVERGENT_KEYS_PREFIX = "judge_duration_ms"
_KNOWN_DIVERGENT_KEY = "duration_ms"


class _StubProvider:
    model = "stub-judge-model"


class StubJudge:
    """Deterministic stand-in for `AnswerJudge`.

    Returns canned rubric scores keyed by `case.id` so identical synthetic input produces
    identical judged output whether it is driven through `AnswerReportJudge.judge_payload()`
    or through the rejudge script's `process()`.
    """

    DEFAULT_PROMPT_PATH = Path("prompts/code-answer-judge.md")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.prompt_path = self.DEFAULT_PROMPT_PATH
        self.provider = _StubProvider()

    def judge(self, case: Any, prediction: str, context: str) -> dict[str, Any]:
        overall = CASE_OVERALL[case.id]
        scores = {f"judge_{name}": overall for name in JUDGE_CRITERIA}
        scores["judge_overall"] = overall
        scores["judge_abstained"] = 0.0
        scores["judge_empty_answer"] = 0.0
        return {
            "scores": scores,
            "questionnaire": {},
            "rationale": "stub",
            "critical_issues": [],
            "prompt_path": str(self.prompt_path),
            "model": _StubProvider.model,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REJUDGE = load_script("rejudge_answer_report")


def make_rows() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "case-0",
            "question": "What does case-0 do?",
            "reference": "reference-0",
            "prediction": "prediction-0",
            "context_text": "=== a.py ===\ndef a(): ...",
            "metadata": {},
            "expected_paths": ["a.py"],
            "metrics": {
                "context_bundle_complete": 1.0,
                "answer_grounded": 1.0,
                "candidate_file_hit": 1.0,
                "token_f1": 0.9,
            },
        },
        {
            "case_id": "case-1",
            "question": "What does case-1 do?",
            "reference": "reference-1",
            "prediction": "prediction-1",
            "context_text": "=== b.py ===\ndef b(): ...",
            "metadata": {},
            "expected_paths": ["b.py"],
            "metrics": {
                "context_bundle_complete": 0.0,
                "answer_grounded": 0.0,
                "candidate_file_hit": 1.0,
                "token_f1": 0.4,
            },
        },
        {
            "case_id": "case-2",
            "question": "What does case-2 do?",
            "reference": "reference-2",
            "prediction": "prediction-2",
            "context_text": "=== c.py ===\ndef c(): ...",
            "metadata": {},
            "expected_paths": ["c.py"],
            "metrics": {
                "context_bundle_complete": 1.0,
                "answer_grounded": 1.0,
                "candidate_file_hit": 0.0,
                "token_f1": 0.6,
            },
        },
    ]


def make_error_row() -> dict[str, Any]:
    """A row whose generation step failed: empty `prediction` plus a pre-existing `error`.

    This is the shape `AnswerEvaluator._evaluate_case()` writes when the answer model's
    JSON response failed to parse (see `answer_evaluator.py`): `prediction` stays `""`
    and a top-level `error` key is set, and -- critically -- the judge is never called for
    it during the original evaluation run. A rejudge should honor that.
    """
    return {
        "case_id": "case-err",
        "question": "What does case-err do?",
        "reference": "reference-err",
        "prediction": "",
        "context_text": "=== e.py ===\ndef e(): ...",
        "metadata": {},
        "expected_paths": ["e.py"],
        "error": "generation failed: invalid json",
        "metrics": {
            "context_bundle_complete": 0.0,
            "answer_grounded": 0.0,
            "candidate_file_hit": 0.0,
            "token_f1": 0.0,
        },
    }


def _strip_known_divergences(metrics: dict[str, float]) -> dict[str, float]:
    return {
        key: value
        for key, value in metrics.items()
        if key != _KNOWN_DIVERGENT_KEY and not key.startswith(_KNOWN_DIVERGENT_KEYS_PREFIX)
    }


def run_rejudge_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    source = {"results": rows if rows is not None else make_rows()}
    input_path = tmp_path / "source.json"
    input_path.write_text(json.dumps(source), encoding="utf-8")
    output_path = tmp_path / "rejudged.json"

    monkeypatch.setattr(REJUDGE, "AnswerJudge", StubJudge)
    monkeypatch.setattr(REJUDGE, "create_generation_provider", lambda config: _StubProvider())
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
    return json.loads(output_path.read_text(encoding="utf-8"))


def test_rejudged_report_retains_deterministic_metric_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejudged = run_rejudge_script(tmp_path, monkeypatch)
    metrics = rejudged["metrics"]
    for key in DETERMINISTIC_METRICS:
        assert key in metrics, f"{key!r} was dropped from the rejudged aggregate"


def test_rejudged_report_has_judge_overall_confidence_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejudged = run_rejudge_script(tmp_path, monkeypatch)
    metrics = rejudged["metrics"]
    assert "judge_overall_ci95_low" in metrics
    assert "judge_overall_ci95_high" in metrics
    assert metrics["judge_overall_ci95_low"] <= metrics["judge_overall"] <= metrics["judge_overall_ci95_high"]


def test_rejudged_report_binary_metrics_get_wilson_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejudged = run_rejudge_script(tmp_path, monkeypatch)
    metrics = rejudged["metrics"]
    assert "context_bundle_complete_ci95_low" in metrics
    assert 0.0 <= metrics["context_bundle_complete_ci95_low"] <= 1.0
    assert 0.0 <= metrics["context_bundle_complete_ci95_high"] <= 1.0


def test_rejudge_script_and_answer_report_judge_agree_on_synthetic_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejudged = run_rejudge_script(tmp_path, monkeypatch)

    live_payload = AnswerReportJudge(judge=StubJudge()).judge_payload({"results": make_rows()})

    rejudged_metrics = _strip_known_divergences(rejudged["metrics"])
    live_metrics = _strip_known_divergences(live_payload["metrics"])

    assert set(rejudged_metrics) == set(live_metrics)
    assert rejudged_metrics == live_metrics


def test_rejudge_script_and_answer_report_judge_agree_on_generation_error_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both judging paths now agree on a row where generation already failed.

    Before `unjudgeable_row_policy` existed, a row with an empty prediction and a
    top-level `error` (the shape `AnswerEvaluator` writes on a parse failure) was handled
    differently by the two paths: the rejudge script silently skipped it (no `judge_*`
    keys at all), while `AnswerReportJudge._judge_row()` called the judge model on it
    anyway. Both now route it through `unjudgeable_row_policy.synthesize_judgment()`
    instead: neither calls `StubJudge.judge()` for it (see `CASE_OVERALL`'s comment), both
    attach a synthesized, zeroed `judge` block, and both include it in the aggregate.
    """
    rows = [make_rows()[0], make_error_row()]

    rejudged = run_rejudge_script(tmp_path, monkeypatch, rows=rows)
    rejudged_error_row = next(row for row in rejudged["results"] if row["case_id"] == "case-err")

    live_payload = AnswerReportJudge(judge=StubJudge()).judge_payload({"results": rows})
    live_error_row = next(row for row in live_payload["results"] if row["case_id"] == "case-err")

    for error_row in (rejudged_error_row, live_error_row):
        assert error_row["judge"]["synthesized"] is True
        assert error_row["metrics"]["judge_overall"] == 0.0
        assert error_row["metrics"]["judge_empty_answer"] == 1.0
        assert error_row["metrics"]["judge_abstained"] == 0.0
        assert "judge_error" not in error_row

    assert rejudged["judge_error_count"] == 0
    assert live_payload["judge_error_count"] == 0
    # `judge_overall` is present on every row (case-0 was judged for real, case-err was
    # synthesized as a zero), so it contributes to the mean over the full row set rather
    # than being excluded as a missing measurement.
    assert rejudged["metrics"]["judge_scored_count"] == 2.0
    assert live_payload["metrics"]["judge_scored_count"] == 2.0
    assert rejudged["metrics"]["judge_overall"] == pytest.approx(CASE_OVERALL["case-0"] / 2)
    assert live_payload["metrics"]["judge_overall"] == pytest.approx(CASE_OVERALL["case-0"] / 2)
