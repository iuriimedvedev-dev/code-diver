from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load_script("build_judge_anchor_set")
VALIDATE = load_script("validate_judge")


def report_row(case_id: str, overall: float, complete: bool) -> dict:
    return {
        "case_id": case_id,
        "question": f"question {case_id}",
        "reference": "reference",
        "prediction": "prediction",
        "expected_paths": ["src/example.py"],
        "citations": ["src/example.py:1"],
        "metrics": {"context_bundle_complete": 1.0 if complete else 0.0},
        "judge": {"scores": {criterion: 2 for criterion in BUILD.CRITERIA} | {"judge_overall": overall}},
    }


def test_sampling_is_deterministic_stratified_and_bounded() -> None:
    report = {"results": [report_row(f"case-{i:02d}", float(i % 5), i % 2 == 0) for i in range(18)]}
    first, counts, fallback = BUILD.build_anchor_rows(report, "report.json", size=7, seed=19)
    second, _, _ = BUILD.build_anchor_rows(report, "report.json", size=7, seed=19)

    assert [row["case_id"] for row in first] == [row["case_id"] for row in second]
    assert len(first) == 7
    assert sum(counts.values()) == 7
    assert fallback is False
    assert {row["context_bundle_complete"] for row in first} == {True, False}


def test_markdown_does_not_reveal_machine_scores() -> None:
    rows, _, _ = BUILD.build_anchor_rows({"results": [report_row("case", 4, True)]}, "report.json", 1, 0)
    markdown = BUILD.render_markdown(rows)
    assert '"judge_overall"' not in markdown
    assert "judge_overall: 4" not in markdown
    assert "__ / 4" in markdown
    assert "Human scoring" in markdown


def test_validation_reports_bias_mad_and_exact_agreement() -> None:
    rows = []
    for i in range(3):
        human = {criterion: 2 for criterion in VALIDATE.CRITERIA} | {"answer_type": "substantive", "notes": ""}
        machine = {criterion: 3 for criterion in VALIDATE.CRITERIA} | {"judge_overall": 3.75}
        rows.append({"case_id": str(i), "human": human, "machine_scores": machine})
    report = VALIDATE.validate_rows(rows, min_labelled=3)
    stats = report["criteria"]["judge_answer_correctness"]
    assert stats["bias"] == pytest.approx(1.0)
    assert stats["mean_absolute_deviation"] == pytest.approx(1.0)
    assert stats["exact_agreement_rate"] == pytest.approx(0.0)


def test_halo_probe_fires_for_collapsed_machine_scores() -> None:
    rows = []
    for i in range(6):
        human = {criterion: (i + position) % 5 for position, criterion in enumerate(VALIDATE.CRITERIA)}
        human["answer_type"] = "substantive"
        machine = {criterion: i % 5 for criterion in VALIDATE.CRITERIA} | {"judge_overall": float(i)}
        rows.append({"case_id": str(i), "human": human, "machine_scores": machine})
    report = VALIDATE.validate_rows(rows, min_labelled=3)
    assert report["halo_effect_probe"]["fires"] is True
