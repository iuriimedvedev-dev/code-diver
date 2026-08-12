"""Matched-pair comparator for two answer-evaluation reports over the same cases.

Why this exists: an experiment series (H15, H16 arms b/c/d) compares each arm against a
baseline, and the two report JSONs are not guaranteed to cover the same cases -- a live run
writes a `.partial.json` with fewer rows than the completed baseline it will eventually
replace. Averaging a 100-case baseline against an 80-case partial arm silently compares two
different populations and has already produced a wrong conclusion once. This script makes the
correct comparison -- intersect on `case_id`, then compare only the shared cases -- the easy
one, and refuses to run at all when the intersection is empty.

`context_bundle_complete` rises mechanically whenever the context budget is widened (more room,
more expected files fit), so it is a mechanism check, not evidence that an arm improved anything.
`candidate_bundle_complete` is a retrieval metric computed upstream of the context budget and
should not move with it; if it does move, that is query-planner nondeterminism -- see the footer
this script prints.

Usage:
    compare_arm_runs.py baseline.json arm.json [--label-baseline B] [--label-arm A]
                        [--metrics M [M ...]] [--json-out PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

Z_SCORE_95 = 1.96
BINARY_VALUES = frozenset({0.0, 1.0})

# Order matters here: it is the print order. `citation_expected_recall` is the pre-registered
# primary metric (see .session/2026-08-04_h15-context-budget-result.md, "Metric commitment for
# H16") and must be reported first; the guardrail and mechanism check follow it; the remaining
# metrics -- including the saturated `context_bundle_complete` and the continuity-only
# `answer_grounded` -- are reported after for context but are not ranking criteria.
DEFAULT_METRICS: tuple[str, ...] = (
    "citation_expected_recall",
    "citation_fabricated_rate",
    "candidate_bundle_complete",
    "context_bundle_complete",
    "candidate_file_recall",
    "answer_grounded",
    "context_files_count",
    "retrieved_files_count",
)

# Role labels for the metric commitment pre-registered for H16 (multi-path interventions).
# Metrics not in this mapping carry no role label -- they are reported for context only.
METRIC_ROLE_LABELS: dict[str, str] = {
    "citation_expected_recall": "(primary)",
    "citation_fabricated_rate": "(guardrail)",
    "candidate_bundle_complete": "(mechanism)",
    "answer_grounded": "(continuity -- not for ranking)",
}


def label_metric(name: str) -> str:
    role = METRIC_ROLE_LABELS.get(name)
    return f"{name} {role}" if role else name


FOOTER = (
    "\nnote: per the H16 metric commitment, rank arms on citation_expected_recall (primary) --\n"
    "the fraction of expected paths actually cited. citation_fabricated_rate is a guardrail:\n"
    "it must not worsen, regardless of the primary result. candidate_bundle_complete is the\n"
    "mechanism check (context_bundle_complete is now saturated at the candidate ceiling and is\n"
    "no longer informative as one). answer_grounded is retained for continuity but is NOT a\n"
    "ranking criterion for multi-path interventions -- it is structurally blind to gains on the\n"
    "second-plus expected path (see Finding 9)."
)


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or "results" not in report:
        raise ValueError(f"{path}: missing top-level 'results' list")
    if not isinstance(report["results"], list):
        raise ValueError(f"{path}: 'results' must be a list")
    return report


def index_rows_by_case_id(rows: list[dict[str, Any]], source: str) -> dict[str, dict[str, Any]]:
    """case_id -> row. Fails fast: a row without a case_id cannot be matched to anything."""
    indexed: dict[str, dict[str, Any]] = {}
    for position, row in enumerate(rows):
        case_id = row.get("case_id")
        if not case_id:
            raise ValueError(f"{source}: row {position} is missing 'case_id'")
        indexed[str(case_id)] = row
    return indexed


def matched_case_ids(
    baseline_rows: dict[str, dict[str, Any]], arm_rows: dict[str, dict[str, Any]]
) -> tuple[list[str], int, int]:
    """Shared case_ids plus the counts dropped from each side -- the drop counts are what
    catch a baseline/arm pair drawn from mismatched populations before any mean is trusted."""
    shared = sorted(set(baseline_rows) & set(arm_rows))
    baseline_only = len(set(baseline_rows) - set(arm_rows))
    arm_only = len(set(arm_rows) - set(baseline_rows))
    return shared, baseline_only, arm_only


def paired_metric_values(
    baseline_rows: dict[str, dict[str, Any]],
    arm_rows: dict[str, dict[str, Any]],
    case_ids: list[str],
    metric: str,
) -> list[tuple[float, float]]:
    """Pairs where BOTH sides have the metric key. A missing key is excluded, never treated
    as 0.0 -- defaulting it would quietly understate whichever side is missing more keys."""
    pairs: list[tuple[float, float]] = []
    for case_id in case_ids:
        baseline_metrics = baseline_rows[case_id].get("metrics") or {}
        arm_metrics = arm_rows[case_id].get("metrics") or {}
        if metric not in baseline_metrics or metric not in arm_metrics:
            continue
        baseline_value, arm_value = baseline_metrics[metric], arm_metrics[metric]
        if isinstance(baseline_value, (int, float)) and isinstance(arm_value, (int, float)):
            pairs.append((float(baseline_value), float(arm_value)))
    return pairs


def is_binary_metric(pairs: list[tuple[float, float]]) -> bool:
    """True only when every matched value on BOTH sides is exactly 0.0 or 1.0."""
    return bool(pairs) and all(value in BINARY_VALUES for pair in pairs for value in pair)


def wilson_interval(proportion: float, n: int) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    z = Z_SCORE_95
    denominator = 1.0 + z * z / n
    center = (proportion + z * z / (2 * n)) / denominator
    radius = z * math.sqrt((proportion * (1.0 - proportion) + z * z / (4 * n)) / n) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def sign_test_p_value(up: int, down: int) -> float:
    """Two-sided exact binomial sign test over the discordant pairs only."""
    discordant = up + down
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(max(up, down), discordant + 1))
    return min(1.0, 2 * tail / (2**discordant))


def normal_ci_for_paired_diff(deltas: list[float]) -> tuple[float, float] | None:
    n = len(deltas)
    if n < 2:
        return None
    mean = fmean(deltas)
    radius = Z_SCORE_95 * stdev(deltas) / math.sqrt(n)
    return mean - radius, mean + radius


def compute_metric_stats(name: str, pairs: list[tuple[float, float]]) -> dict[str, Any]:
    n = len(pairs)
    if n == 0:
        return {"metric": name, "n": 0, "binary": False, "baseline_mean": None, "arm_mean": None, "delta": None}
    baseline_values = [baseline for baseline, _ in pairs]
    arm_values = [arm for _, arm in pairs]
    baseline_mean, arm_mean = fmean(baseline_values), fmean(arm_values)
    stats: dict[str, Any] = {
        "metric": name,
        "n": n,
        "binary": is_binary_metric(pairs),
        "baseline_mean": baseline_mean,
        "arm_mean": arm_mean,
        "delta": arm_mean - baseline_mean,
    }
    if stats["binary"]:
        up = sum(1 for baseline, arm in pairs if baseline == 0.0 and arm == 1.0)
        down = sum(1 for baseline, arm in pairs if baseline == 1.0 and arm == 0.0)
        stats.update(
            {
                "baseline_ci": wilson_interval(baseline_mean, n),
                "arm_ci": wilson_interval(arm_mean, n),
                "up": up,
                "down": down,
                "sign_test_p": sign_test_p_value(up, down),
            }
        )
    else:
        stats["diff_ci"] = normal_ci_for_paired_diff([arm - baseline for baseline, arm in pairs])
    return stats


def mean_duration_ms(rows_by_case: dict[str, dict[str, Any]], case_ids: list[str]) -> float | None:
    values = [
        float(duration)
        for case_id in case_ids
        if isinstance((duration := rows_by_case[case_id].get("duration_ms")), (int, float))
    ]
    return fmean(values) if values else None


def error_row_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if row.get("error"))


# Stage timings, in the order they are printed. The four named stages plus `other` partition
# `total` exactly, so the share column always sums to 1.0 and nothing can hide in a gap.
STAGE_NAMES: tuple[str, ...] = ("plan", "search", "rerank", "generation", "other", "total")


def _millis(payload: dict[str, Any], key: str) -> float:
    return float(payload.get(key) or 0.0)


def stage_seconds(row: dict[str, Any], stage: str) -> float:
    metrics = row.get("metrics") or {}
    plan_payload = row.get("query_plan") or {}
    total = _millis(row, "duration_ms")
    # `planning_duration_ms` / `rerank_duration_ms` are copies of the query_plan payload; older
    # reports predate the metrics keys, so fall back to the payload they were copied from.
    plan = _millis(metrics, "planning_duration_ms") or _millis(plan_payload, "duration_ms")
    rerank = _millis(metrics, "rerank_duration_ms") or _millis(
        plan_payload.get("final_rerank") or {}, "duration_ms"
    )
    # Retrieval is the whole agentic loop -- planning and the final rerank happen inside it --
    # so the probe searches themselves are what is left after removing those two.
    search = max(_millis(metrics, "retrieval_duration_ms") - plan - rerank, 0.0)
    generation = _millis(metrics, "generation_duration_ms")
    by_stage = {
        "plan": plan,
        "search": search,
        "rerank": rerank,
        "generation": generation,
        "other": total - plan - search - rerank - generation,
        "total": total,
    }
    return by_stage[stage] / 1000


def stage_latency_stats(
    baseline_by_case: dict[str, dict[str, Any]],
    arm_by_case: dict[str, dict[str, Any]],
    case_ids: list[str],
) -> list[dict[str, Any]]:
    """Paired per-stage seconds plus each stage's share of its own run's total.

    The share column is the one to compare across arms. Two runs of an identical config came in
    6.7% apart on every stage at once -- a uniform machine-state factor, not a workload effect
    (Finding 37 in .session/2026-08-05_h17-corpus-and-data-loss.md). A multiplicative factor
    cancels in a ratio, so shares are comparable across runs recorded hours apart and absolute
    seconds are not.
    """
    stats: list[dict[str, Any]] = []
    baseline_total = sum(stage_seconds(baseline_by_case[cid], "total") for cid in case_ids)
    arm_total = sum(stage_seconds(arm_by_case[cid], "total") for cid in case_ids)
    for stage in STAGE_NAMES:
        baseline = [stage_seconds(baseline_by_case[cid], stage) for cid in case_ids]
        arm = [stage_seconds(arm_by_case[cid], stage) for cid in case_ids]
        deltas = [arm[i] - baseline[i] for i in range(len(case_ids))]
        stats.append(
            {
                "stage": stage,
                "baseline_seconds": fmean(baseline) if baseline else None,
                "arm_seconds": fmean(arm) if arm else None,
                "delta_seconds": fmean(deltas) if deltas else None,
                "delta_ci": normal_ci_for_paired_diff(deltas),
                "baseline_share": (sum(baseline) / baseline_total) if baseline_total else None,
                "arm_share": (sum(arm) / arm_total) if arm_total else None,
            }
        )
    return stats


def format_ci(ci: tuple[float, float] | None) -> str:
    return "n/a" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def print_report(
    metric_stats: list[dict[str, Any]],
    label_baseline: str,
    label_arm: str,
    baseline_duration: float | None,
    arm_duration: float | None,
    baseline_errors: int,
    arm_errors: int,
    stage_stats: list[dict[str, Any]] | None = None,
) -> None:
    binary_stats = [stats for stats in metric_stats if stats["binary"]]
    continuous_stats = [stats for stats in metric_stats if not stats["binary"]]

    # Continuous metrics print first: the pre-registered primary metric,
    # citation_expected_recall, is continuous and must be reported before everything else.
    if continuous_stats:
        print(f"\n-- continuous metrics ({label_baseline} vs {label_arm}) --")
        print(f"  {'metric':<28} {'n':>4} {label_baseline:>10} {label_arm:>10} {'delta':>9}  {'95% CI (delta)'}")
        for stats in continuous_stats:
            metric_cell = label_metric(stats["metric"])
            if stats["n"] == 0:
                print(f"    {metric_cell:<26} {'--':>4}")
                continue
            print(
                f"    {metric_cell:<26} {stats['n']:>4} {stats['baseline_mean']:>10.3f} "
                f"{stats['arm_mean']:>10.3f} {stats['delta']:>+9.3f}  {format_ci(stats['diff_ci'])}"
            )

    if binary_stats:
        print(f"\n-- binary metrics ({label_baseline} vs {label_arm}) --")
        print(
            f"  {'metric':<28} {'n':>4} {label_baseline + ' (95% CI)':<24} {label_arm + ' (95% CI)':<24} "
            f"{'delta':>7} {'up':>3} {'down':>5} {'p':>7}"
        )
        for stats in binary_stats:
            metric_cell = label_metric(stats["metric"])
            if stats["n"] == 0:
                print(f"    {metric_cell:<26} {'--':>4}")
                continue
            baseline_cell = f"{stats['baseline_mean']:.3f} {format_ci(stats['baseline_ci'])}"
            arm_cell = f"{stats['arm_mean']:.3f} {format_ci(stats['arm_ci'])}"
            print(
                f"    {metric_cell:<26} {stats['n']:>4} {baseline_cell:<24} {arm_cell:<24} "
                f"{stats['delta']:>+7.3f} {stats['up']:>3} {stats['down']:>5} {stats['sign_test_p']:>7.4f}"
            )

    if stage_stats:
        print(f"\n-- stage latency (matched cases, {label_baseline} vs {label_arm}) --")
        print(
            f"  {'stage':<12} {label_baseline + ' s':>12} {label_arm + ' s':>12} {'delta s':>9}  "
            f"{'95% CI (delta)':<22} {'share ' + label_baseline:>18} {'share ' + label_arm:>18}"
        )
        for stats in stage_stats:
            baseline_share = stats["baseline_share"]
            arm_share = stats["arm_share"]
            share_baseline_cell = "n/a" if baseline_share is None else f"{baseline_share:.1%}"
            share_arm_cell = "n/a" if arm_share is None else f"{arm_share:.1%}"
            print(
                f"    {stats['stage']:<10} {stats['baseline_seconds']:>12.2f} {stats['arm_seconds']:>12.2f} "
                f"{stats['delta_seconds']:>+9.2f}  {format_ci(stats['delta_ci']):<22} "
                f"{share_baseline_cell:>18} {share_arm_cell:>18}"
            )
        print(
            "  Compare the share columns across arms, not the seconds. Two runs of an identical\n"
            "  config landed 6.7% apart on every stage at once -- machine state applies a uniform\n"
            "  multiplicative factor to wall-clock, and that factor cancels in a ratio."
        )

    print("\n-- cost / errors (matched cases) --")
    baseline_duration_cell = "n/a" if baseline_duration is None else f"{baseline_duration:.0f} ms"
    arm_duration_cell = "n/a" if arm_duration is None else f"{arm_duration:.0f} ms"
    print(f"  duration_ms mean       {label_baseline:<16} {baseline_duration_cell:>12}")
    print(f"                         {label_arm:<16} {arm_duration_cell:>12}")
    print(f"  error rows (full report)  {label_baseline:<16} {baseline_errors:>12}")
    print(f"                            {label_arm:<16} {arm_errors:>12}")
    print(FOOTER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("arm", type=Path)
    parser.add_argument("--label-baseline", default=None)
    parser.add_argument("--label-arm", default=None)
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_METRICS))
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    label_baseline = args.label_baseline or args.baseline.stem
    label_arm = args.label_arm or args.arm.stem

    baseline_report = load_report(args.baseline)
    arm_report = load_report(args.arm)
    baseline_rows_by_case = index_rows_by_case_id(baseline_report["results"], str(args.baseline))
    arm_rows_by_case = index_rows_by_case_id(arm_report["results"], str(args.arm))

    shared_ids, baseline_only, arm_only = matched_case_ids(baseline_rows_by_case, arm_rows_by_case)
    if not shared_ids:
        print(f"No overlapping case_id between {args.baseline} and {args.arm} -- nothing to compare.", file=sys.stderr)
        return 1

    print(
        f"matched cases: {len(shared_ids)}  "
        f"(dropped {baseline_only} present only in {label_baseline}, {arm_only} present only in {label_arm})"
    )

    metric_stats = [
        compute_metric_stats(metric, paired_metric_values(baseline_rows_by_case, arm_rows_by_case, shared_ids, metric))
        for metric in args.metrics
    ]
    baseline_duration = mean_duration_ms(baseline_rows_by_case, shared_ids)
    arm_duration = mean_duration_ms(arm_rows_by_case, shared_ids)
    baseline_errors = error_row_count(baseline_report["results"])
    arm_errors = error_row_count(arm_report["results"])
    stage_stats = stage_latency_stats(baseline_rows_by_case, arm_rows_by_case, shared_ids)

    print_report(
        metric_stats,
        label_baseline,
        label_arm,
        baseline_duration,
        arm_duration,
        baseline_errors,
        arm_errors,
        stage_stats,
    )

    if args.json_out:
        payload = {
            "baseline": str(args.baseline),
            "arm": str(args.arm),
            "label_baseline": label_baseline,
            "label_arm": label_arm,
            "matched_cases": len(shared_ids),
            "baseline_only": baseline_only,
            "arm_only": arm_only,
            "metrics": metric_stats,
            "duration_ms": {"baseline_mean": baseline_duration, "arm_mean": arm_duration},
            "stage_latency": stage_stats,
            "errors": {"baseline_count": baseline_errors, "arm_count": arm_errors},
        }
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
