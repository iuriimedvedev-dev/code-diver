from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPARE = load_script("compare_arm_runs")


def row(case_id: str, metrics: dict[str, Any], *, duration_ms: float = 100.0, error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"case_id": case_id, "metrics": metrics, "duration_ms": duration_ms}
    if error is not None:
        payload["error"] = error
    return payload


def test_non_overlapping_case_ids_have_empty_intersection() -> None:
    baseline = COMPARE.index_rows_by_case_id([row("a", {}), row("b", {})], "baseline")
    arm = COMPARE.index_rows_by_case_id([row("c", {}), row("d", {})], "arm")
    shared, baseline_only, arm_only = COMPARE.matched_case_ids(baseline, arm)
    assert shared == []
    assert baseline_only == 2
    assert arm_only == 2


def test_partial_overlap_compares_only_shared_ids() -> None:
    baseline = COMPARE.index_rows_by_case_id(
        [row("a", {"m": 1.0}), row("b", {"m": 0.0}), row("c", {"m": 1.0})], "baseline"
    )
    arm = COMPARE.index_rows_by_case_id([row("a", {"m": 0.0}), row("b", {"m": 1.0})], "arm")
    shared, baseline_only, arm_only = COMPARE.matched_case_ids(baseline, arm)
    assert shared == ["a", "b"]
    assert baseline_only == 1
    assert arm_only == 0

    pairs = COMPARE.paired_metric_values(baseline, arm, shared, "m")
    assert pairs == [(1.0, 0.0), (0.0, 1.0)]


def test_metric_missing_on_one_side_is_excluded_from_n_not_defaulted_to_zero() -> None:
    baseline = COMPARE.index_rows_by_case_id(
        [row("a", {"m": 1.0}), row("b", {"m": 1.0}), row("c", {})], "baseline"
    )
    arm = COMPARE.index_rows_by_case_id(
        [row("a", {"m": 1.0}), row("b", {}), row("c", {"m": 0.0})], "arm"
    )
    shared, _, _ = COMPARE.matched_case_ids(baseline, arm)
    assert shared == ["a", "b", "c"]

    pairs = COMPARE.paired_metric_values(baseline, arm, shared, "m")
    # only case "a" has the key present on BOTH sides -- "b" and "c" must be excluded, not
    # counted as (1.0, 0.0) or (0.0, 0.0).
    assert pairs == [(1.0, 1.0)]

    stats = COMPARE.compute_metric_stats("m", pairs)
    assert stats["n"] == 1
    assert stats["baseline_mean"] == pytest.approx(1.0)
    assert stats["arm_mean"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("up", "down", "expected"),
    [
        (6, 0, 2 / 64),
        (6, 1, 2 * (7 + 1) / 128),
        (0, 0, 1.0),
    ],
)
def test_sign_test_p_value_matches_known_fixtures(up: int, down: int, expected: float) -> None:
    assert COMPARE.sign_test_p_value(up, down) == pytest.approx(expected)


def test_sign_test_p_value_is_symmetric_in_up_and_down() -> None:
    assert COMPARE.sign_test_p_value(3, 5) == pytest.approx(COMPARE.sign_test_p_value(5, 3))


def test_metric_with_non_binary_values_is_not_treated_as_binary() -> None:
    pairs = [(1.0, 2.0), (0.0, 1.0), (3.0, 0.0)]
    assert COMPARE.is_binary_metric(pairs) is False

    stats = COMPARE.compute_metric_stats("count", pairs)
    assert stats["binary"] is False
    assert "sign_test_p" not in stats
    assert stats["diff_ci"] is not None or len(pairs) < 2


def test_all_zero_one_values_on_both_sides_is_binary() -> None:
    pairs = [(0.0, 1.0), (1.0, 1.0), (0.0, 0.0)]
    assert COMPARE.is_binary_metric(pairs) is True


def test_load_report_requires_results_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"no_results_here": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="results"):
        COMPARE.load_report(path)


def test_index_rows_requires_case_id() -> None:
    with pytest.raises(ValueError, match="case_id"):
        COMPARE.index_rows_by_case_id([{"metrics": {}}], "source.json")


def test_wilson_interval_contains_the_point_estimate() -> None:
    low, high = COMPARE.wilson_interval(0.5, 20)
    assert low < 0.5 < high


def test_compute_metric_stats_reports_up_down_and_p_for_binary_metric() -> None:
    pairs = [(0.0, 1.0)] * 6 + [(1.0, 1.0)] * 2
    stats = COMPARE.compute_metric_stats("flag", pairs)
    assert stats["binary"] is True
    assert stats["up"] == 6
    assert stats["down"] == 0
    assert stats["sign_test_p"] == pytest.approx(2 / 64)


def test_main_exits_nonzero_when_intersection_is_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json
    import sys

    baseline_path = tmp_path / "baseline.json"
    arm_path = tmp_path / "arm.json"
    baseline_path.write_text(json.dumps({"results": [row("a", {"m": 1.0})]}), encoding="utf-8")
    arm_path.write_text(json.dumps({"results": [row("z", {"m": 1.0})]}), encoding="utf-8")

    argv = sys.argv
    sys.argv = ["compare_arm_runs.py", str(baseline_path), str(arm_path)]
    try:
        exit_code = COMPARE.main()
    finally:
        sys.argv = argv
    assert exit_code == 1


def test_default_metrics_reports_citation_expected_recall_first_as_primary() -> None:
    # Regression for the defect where the pre-registered primary metric
    # (`citation_expected_recall`, per .session/2026-08-04_h15-context-budget-result.md,
    # "Metric commitment for H16") was missing from DEFAULT_METRICS entirely.
    assert COMPARE.DEFAULT_METRICS[0] == "citation_expected_recall"
    assert COMPARE.METRIC_ROLE_LABELS["citation_expected_recall"] == "(primary)"


def test_main_reports_citation_expected_recall_with_correct_paired_delta(tmp_path: Path) -> None:
    import json
    import sys

    baseline_rows = [
        row("a", {"citation_expected_recall": 0.0}),
        row("b", {"citation_expected_recall": 0.5}),
        row("c", {"citation_expected_recall": 1.0}),
    ]
    arm_rows = [
        row("a", {"citation_expected_recall": 1.0}),
        row("b", {"citation_expected_recall": 0.5}),
        row("c", {"citation_expected_recall": 1.0}),
    ]
    baseline_path = tmp_path / "baseline.json"
    arm_path = tmp_path / "arm.json"
    baseline_path.write_text(json.dumps({"results": baseline_rows}), encoding="utf-8")
    arm_path.write_text(json.dumps({"results": arm_rows}), encoding="utf-8")
    json_out = tmp_path / "out.json"

    argv = sys.argv
    sys.argv = [
        "compare_arm_runs.py",
        str(baseline_path),
        str(arm_path),
        "--metrics",
        "citation_expected_recall",
        "--json-out",
        str(json_out),
    ]
    try:
        exit_code = COMPARE.main()
    finally:
        sys.argv = argv

    assert exit_code == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    metric_stats = payload["metrics"][0]
    assert metric_stats["metric"] == "citation_expected_recall"
    assert metric_stats["binary"] is False
    assert metric_stats["baseline_mean"] == pytest.approx(0.5)
    assert metric_stats["arm_mean"] == pytest.approx(2.5 / 3)
    assert metric_stats["delta"] == pytest.approx(1.0 / 3)
    diff_ci = metric_stats["diff_ci"]
    assert diff_ci is not None
    assert diff_ci[0] < metric_stats["delta"] < diff_ci[1]


def test_footer_ranks_on_citation_expected_recall_not_answer_grounded() -> None:
    # Regression for the defect where the footer told readers to rank on `answer_grounded`
    # and `citation_fabricated_rate`, contradicting the pre-registered H16 metric commitment.
    assert "citation_expected_recall" in COMPARE.FOOTER
    assert "rank arms on citation_expected_recall" in COMPARE.FOOTER
    assert "guardrail" in COMPARE.FOOTER
    assert "NOT a" in COMPARE.FOOTER and "ranking criterion" in COMPARE.FOOTER


def test_main_writes_json_out_for_matched_partial_reports(tmp_path: Path) -> None:
    import json
    import sys

    baseline_rows = [row(f"case-{i}", {"answer_grounded": float(i % 2)}) for i in range(5)]
    arm_rows = [row(f"case-{i}", {"answer_grounded": 1.0}) for i in range(3)]
    baseline_path = tmp_path / "baseline.json"
    arm_path = tmp_path / "arm.json"
    baseline_path.write_text(json.dumps({"results": baseline_rows}), encoding="utf-8")
    arm_path.write_text(json.dumps({"results": arm_rows}), encoding="utf-8")
    json_out = tmp_path / "out.json"

    argv = sys.argv
    sys.argv = [
        "compare_arm_runs.py",
        str(baseline_path),
        str(arm_path),
        "--metrics",
        "answer_grounded",
        "--json-out",
        str(json_out),
    ]
    try:
        exit_code = COMPARE.main()
    finally:
        sys.argv = argv

    assert exit_code == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["matched_cases"] == 3
    assert payload["baseline_only"] == 2
    assert payload["arm_only"] == 0
    assert payload["metrics"][0]["metric"] == "answer_grounded"
    assert not math.isnan(payload["metrics"][0]["baseline_mean"])


def timed_row(case_id: str, *, plan: float, retrieval: float, rerank: float, generation: float, total: float) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "duration_ms": total,
        "metrics": {
            "planning_duration_ms": plan,
            "retrieval_duration_ms": retrieval,
            "rerank_duration_ms": rerank,
            "generation_duration_ms": generation,
        },
    }


def scaled(rows: list[dict[str, Any]], factor: float) -> list[dict[str, Any]]:
    return [
        timed_row(
            r["case_id"],
            plan=r["metrics"]["planning_duration_ms"] * factor,
            retrieval=r["metrics"]["retrieval_duration_ms"] * factor,
            rerank=r["metrics"]["rerank_duration_ms"] * factor,
            generation=r["metrics"]["generation_duration_ms"] * factor,
            total=r["duration_ms"] * factor,
        )
        for r in rows
    ]


def test_named_stages_partition_the_total_exactly() -> None:
    # If they did not, time could hide in a gap and the share column would mislead.
    r = timed_row("a", plan=7000, retrieval=20000, rerank=12000, generation=30000, total=62000)
    parts = sum(COMPARE.stage_seconds(r, stage) for stage in COMPARE.STAGE_NAMES if stage != "total")
    assert parts == pytest.approx(COMPARE.stage_seconds(r, "total"))
    # Retrieval brackets planning and the rerank, so the probe searches are what is left.
    assert COMPARE.stage_seconds(r, "search") == pytest.approx(1.0)


def test_stage_shares_survive_a_uniform_slowdown_that_moves_every_second() -> None:
    # Finding 37: two runs of an identical config landed 6.7% apart on every stage at once.
    # Shares are the drift-immune quantity; this is the property arm verdicts rest on.
    baseline_rows = [timed_row(f"case-{i}", plan=7000, retrieval=20000, rerank=12000, generation=30000, total=62000) for i in range(4)]
    slow_rows = scaled(baseline_rows, 1.30)
    baseline = COMPARE.index_rows_by_case_id(baseline_rows, "baseline")
    slow = COMPARE.index_rows_by_case_id(slow_rows, "arm")
    shared, _, _ = COMPARE.matched_case_ids(baseline, slow)

    stats = {s["stage"]: s for s in COMPARE.stage_latency_stats(baseline, slow, shared)}

    assert stats["rerank"]["arm_share"] == pytest.approx(stats["rerank"]["baseline_share"])
    assert stats["generation"]["arm_share"] == pytest.approx(stats["generation"]["baseline_share"])
    # ... while the seconds moved, and moved detectably: the CI on the delta excludes zero.
    assert stats["total"]["delta_seconds"] == pytest.approx(18.6)
    low, _high = stats["total"]["delta_ci"]
    assert low > 0


def test_a_real_stage_swap_shows_up_in_the_share_column() -> None:
    baseline_rows = [timed_row(f"case-{i}", plan=7000, retrieval=20000, rerank=12000, generation=30000, total=62000) for i in range(4)]
    # A cross-encoder replacing a generative rerank: 12 s -> 1.5 s, everything else untouched.
    arm_rows = [timed_row(f"case-{i}", plan=7000, retrieval=9500, rerank=1500, generation=30000, total=51500) for i in range(4)]
    baseline = COMPARE.index_rows_by_case_id(baseline_rows, "baseline")
    arm = COMPARE.index_rows_by_case_id(arm_rows, "arm")
    shared, _, _ = COMPARE.matched_case_ids(baseline, arm)

    stats = {s["stage"]: s for s in COMPARE.stage_latency_stats(baseline, arm, shared)}

    assert stats["rerank"]["baseline_share"] == pytest.approx(12 / 62, abs=1e-3)
    assert stats["rerank"]["arm_share"] == pytest.approx(1.5 / 51.5, abs=1e-3)


def test_stage_seconds_falls_back_to_the_query_plan_payload_on_older_reports() -> None:
    # Reports written before the metrics keys existed still carry the payload they were copied from.
    legacy = {
        "case_id": "a",
        "duration_ms": 62000,
        "query_plan": {"duration_ms": 7000, "final_rerank": {"duration_ms": 12000}},
    }
    assert COMPARE.stage_seconds(legacy, "plan") == pytest.approx(7.0)
    assert COMPARE.stage_seconds(legacy, "rerank") == pytest.approx(12.0)
    assert COMPARE.stage_seconds(legacy, "search") == pytest.approx(0.0)


def test_search_never_reports_negative_seconds() -> None:
    # Retrieval is measured around planning and the rerank, but they are timed separately;
    # rounding or a retry accounted outside the loop must not produce a negative stage.
    r = timed_row("a", plan=7000, retrieval=18000, rerank=12000, generation=30000, total=62000)
    assert COMPARE.stage_seconds(r, "search") == 0.0
    parts = sum(COMPARE.stage_seconds(r, stage) for stage in COMPARE.STAGE_NAMES if stage != "total")
    assert parts == pytest.approx(COMPARE.stage_seconds(r, "total"))
