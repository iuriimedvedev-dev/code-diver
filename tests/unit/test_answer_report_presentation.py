from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from code_diver.answering import AnswerReportMetrics
from code_diver.answering.answer_report_metrics import JUDGE_METRICS, PRIMARY_METRICS
from code_diver.cli import answer_report_metric_cell, render_answer_metrics_table

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

JUDGE_CRITERIA = (
    "judge_answer_correctness",
    "judge_evidence_grounding",
    "judge_coverage",
    "judge_citation_quality",
    "judge_specificity",
    "judge_hallucination_control",
)


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# DEFAULT_METRICS ordering invariant
# ---------------------------------------------------------------------------


def test_default_metrics_context_bundle_complete_leads() -> None:
    metrics = AnswerReportMetrics.DEFAULT_METRICS
    assert metrics[0] == "context_bundle_complete"


def test_default_metrics_context_bundle_complete_precedes_judge_overall() -> None:
    metrics = AnswerReportMetrics.DEFAULT_METRICS
    assert metrics.index("context_bundle_complete") < metrics.index("judge_overall")


def test_default_metrics_contains_all_six_judge_criteria() -> None:
    metrics = set(AnswerReportMetrics.DEFAULT_METRICS)
    for criterion in JUDGE_CRITERIA:
        assert criterion in metrics


def test_default_metrics_has_no_duplicate_keys() -> None:
    metrics = AnswerReportMetrics.DEFAULT_METRICS
    assert len(metrics) == len(set(metrics))


def test_default_metrics_judge_overall_is_last_judge_metric() -> None:
    assert JUDGE_METRICS[-1] == "judge_overall"


def test_default_metrics_never_includes_a_criteria_sum_key() -> None:
    metrics = AnswerReportMetrics.DEFAULT_METRICS
    assert not any("sum" in key.lower() for key in metrics)


def test_default_metrics_is_primary_then_judge_metrics() -> None:
    assert list(AnswerReportMetrics.DEFAULT_METRICS[: len(PRIMARY_METRICS)]) == list(PRIMARY_METRICS)
    offset = len(PRIMARY_METRICS)
    assert list(AnswerReportMetrics.DEFAULT_METRICS[offset : offset + len(JUDGE_METRICS)]) == list(JUDGE_METRICS)


# ---------------------------------------------------------------------------
# AnswerReportMetrics.summarize() still recomputes from rows correctly
# ---------------------------------------------------------------------------


def test_answer_report_metrics_recomputes_aggregate_with_new_ordering() -> None:
    payload = {
        "metrics": {"context_bundle_complete": 0.0},
        "results": [
            {"metrics": {"context_bundle_complete": 1.0, "file_hit": 1.0, "token_f1": 0.2}},
            {"metrics": {"context_bundle_complete": 0.0, "file_hit": 0.0, "token_f1": 0.4}},
        ],
    }

    summary = AnswerReportMetrics().summarize(payload)

    assert summary["metrics"]["cases"] == 2.0
    assert summary["metrics"]["context_bundle_complete"] == 0.5
    assert summary["metrics"]["file_hit"] == 0.5
    assert summary["metrics"]["token_f1"] == pytest.approx(0.3)
    assert "context_bundle_complete_ci95_low" in summary["metrics"]


# ---------------------------------------------------------------------------
# Cell renderer
# ---------------------------------------------------------------------------


def test_cell_renderer_emits_ci_for_context_bundle_complete() -> None:
    metrics = {
        "context_bundle_complete": 0.42,
        "context_bundle_complete_ci95_low": 0.30,
        "context_bundle_complete_ci95_high": 0.55,
    }

    cell = answer_report_metric_cell(metrics, "context_bundle_complete")

    assert "0.420" in cell
    assert "[0.300, 0.550]" in cell


def test_cell_renderer_falls_back_without_ci_data() -> None:
    cell = answer_report_metric_cell({"context_bundle_complete": 0.42}, "context_bundle_complete")
    assert cell == "0.4200"


def test_cell_renderer_missing_key_is_a_dash() -> None:
    assert answer_report_metric_cell({}, "context_bundle_complete") == "-"


# ---------------------------------------------------------------------------
# Missing judge_abstained does not crash the renderer
# ---------------------------------------------------------------------------


def test_render_answer_metrics_table_skips_missing_judge_abstained(capsys: pytest.CaptureFixture[str]) -> None:
    metrics = {
        "cases": 2.0,
        "context_bundle_complete": 0.5,
        "judge_answer_correctness": 3.0,
        "judge_overall": 3.2,
        # judge_abstained deliberately absent -- older reports won't have it.
    }

    render_answer_metrics_table(metrics)

    output = capsys.readouterr().out
    assert "judge_abstained" not in output
    assert "context_bundle_complete" in output


def test_render_answer_metrics_table_renders_judge_abstained_when_present(
    capsys: pytest.CaptureFixture[str],
) -> None:
    metrics = {
        "cases": 2.0,
        "context_bundle_complete": 0.5,
        "judge_abstained": 0.1,
        "judge_overall": 3.2,
    }

    render_answer_metrics_table(metrics)

    output = capsys.readouterr().out
    assert "judge_abstained" in output


# ---------------------------------------------------------------------------
# scripts/compare_judges.py per-criterion comparison math
# ---------------------------------------------------------------------------

COMPARE_JUDGES = load_script("compare_judges")


def _report(path, rows: list[dict]) -> None:
    import json

    path.write_text(json.dumps({"results": rows}), encoding="utf-8")


def test_compare_judges_reports_per_criterion_agreement_without_a_sum(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.json"
    candidate_path = tmp_path / "candidate.json"
    _report(
        reference_path,
        [
            {
                "case_id": "a",
                "judge": {
                    "scores": {
                        "judge_answer_correctness": 4.0,
                        "judge_evidence_grounding": 3.0,
                        "judge_coverage": 4.0,
                        "judge_citation_quality": 2.0,
                        "judge_specificity": 3.0,
                        "judge_hallucination_control": 4.0,
                        "judge_overall": 4.5,
                        "judge_abstained": 0.0,
                    }
                },
            },
            {
                "case_id": "b",
                "judge": {
                    "scores": {
                        "judge_answer_correctness": 2.0,
                        "judge_evidence_grounding": 2.0,
                        "judge_coverage": 2.0,
                        "judge_citation_quality": 1.0,
                        "judge_specificity": 1.0,
                        "judge_hallucination_control": 2.0,
                        "judge_overall": 2.0,
                        "judge_abstained": 1.0,
                    }
                },
            },
        ],
    )
    _report(
        candidate_path,
        [
            {
                "case_id": "a",
                "judge": {
                    "scores": {
                        "judge_answer_correctness": 4.0,
                        "judge_evidence_grounding": 4.0,
                        "judge_coverage": 4.0,
                        "judge_citation_quality": 3.0,
                        "judge_specificity": 3.0,
                        "judge_hallucination_control": 4.0,
                        "judge_overall": 4.8,
                        "judge_abstained": 0.0,
                    }
                },
            },
            {
                "case_id": "b",
                "judge": {
                    "scores": {
                        "judge_answer_correctness": 3.0,
                        "judge_evidence_grounding": 2.0,
                        "judge_coverage": 2.0,
                        "judge_citation_quality": 2.0,
                        "judge_specificity": 1.0,
                        "judge_hallucination_control": 2.0,
                        "judge_overall": 2.5,
                        "judge_abstained": 1.0,
                    }
                },
            },
        ],
    )

    result = COMPARE_JUDGES.compare_pair(reference_path, candidate_path)

    assert not hasattr(COMPARE_JUDGES, "criteria_sum")
    assert not hasattr(COMPARE_JUDGES, "SUM_CRITERIA_MAX")
    assert "criteria" in result and "sum_reference_mean" not in result

    correctness = result["criteria"]["judge_answer_correctness"]
    assert correctness["cases"] == 2
    assert correctness["reference_mean"] == pytest.approx(3.0)
    assert correctness["candidate_mean"] == pytest.approx(3.5)
    assert correctness["bias"] == pytest.approx(0.5)

    abstention = result["abstention"]
    assert abstention is not None
    assert abstention["cases"] == 2
    assert abstention["agreement_rate"] == pytest.approx(1.0)
    assert abstention["both_abstained"] == 1


def test_compare_judges_abstention_is_none_when_key_absent(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.json"
    candidate_path = tmp_path / "candidate.json"
    row = {
        "case_id": "a",
        "judge": {"scores": {"judge_answer_correctness": 4.0, "judge_overall": 4.0}},
    }
    _report(reference_path, [row])
    _report(candidate_path, [row])

    result = COMPARE_JUDGES.compare_pair(reference_path, candidate_path)

    assert result["abstention"] is None
