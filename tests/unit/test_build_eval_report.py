from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

_SPEC = importlib.util.spec_from_file_location(
    "build_eval_report",
    Path(__file__).resolve().parents[2] / "scripts" / "build_eval_report.py",
)
assert _SPEC is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
normalize_rows = _MODULE.normalize_rows
render_report = _MODULE.render_report


def test_report_normalizes_experiment_json_shape() -> None:
    rows = normalize_rows(
        {
            "run_id": "run",
            "strategies": [
                {
                    "strategy": "hybrid",
                    "metrics": {
                        "hit_rate@5": 0.8,
                        "hit_rate@5_ci95_low": 0.7,
                        "hit_rate@5_ci95_high": 0.9,
                    },
                    "results": [{"hit": True, "reciprocal_rank": 1.0, "recall": 1.0}],
                }
            ],
        }
    )

    assert rows[0]["name"] == "hybrid"
    assert rows[0]["metrics"]["hit_rate@5"] == 0.8
    assert rows[0]["results"][0]["hit"] is True


def test_report_normalizes_direct_results_json_shape() -> None:
    rows = normalize_rows(
        {
            "run_id": "run",
            "results": [
                {
                    "hypothesis": "agentic",
                    "metrics": {"mrr@10": 0.5},
                    "tools": ["code_diver_search"],
                }
            ],
        }
    )

    assert rows[0]["name"] == "agentic"
    assert rows[0]["tools"] == ["code_diver_search"]


def test_report_normalizes_single_evaluate_json_shape() -> None:
    rows = normalize_rows({"metrics": {"hit_rate@1": 1.0}, "results": []})

    assert rows[0]["name"] == "evaluate"
    assert rows[0]["metrics"]["hit_rate@1"] == 1.0


def test_report_renders_confidence_interval_table() -> None:
    html = render_report(
        [
            {
                "name": "hybrid",
                "metrics": {
                    "hit_rate@5": 0.8,
                    "hit_rate@5_ci95_low": 0.7,
                    "hit_rate@5_ci95_high": 0.9,
                },
                "results": [],
            }
        ],
        {"run_id": "run"},
    )

    assert "Summary With 95% CI" in html
    assert "[0.7000, 0.9000]" in html
