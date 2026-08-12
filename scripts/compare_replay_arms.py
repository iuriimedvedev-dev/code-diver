"""Compare two `replay_pool_recall.py` outputs, path by path, and refuse mismatched provenance.

A replay's probe queries come out of the report it was replayed from, so the source report is
not a label on the run -- it is half the input. Comparing an arm replayed from report A against
a baseline replayed from report B varies something the experiment never meant to vary, and the
headline recall numbers look perfectly reasonable while doing it. That happened: a champion
baseline was replayed from H14's report, and the 0.006 gap it produced got misdiagnosed as GPU
nondeterminism before the provenance was read. Hence the assertion, on by default.

The paired path-level view is the point of the script. Pool recall moves in steps of 1/163 on
this suite, so a delta of a hundredth is two paths; the sign test over discordant paths says
whether that is a result or a coin flip.

Usage:
    compare_replay_arms.py BASELINE ARM [--allow-different-reports]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


class CompareReplayError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ("report", "config", "candidate_limit", "per_case"):
        if key not in payload:
            raise CompareReplayError(f"{path} is not a replay output: missing `{key}`")
    return payload


def check_provenance(baseline: dict[str, Any], arm: dict[str, Any], allow: bool) -> list[str]:
    """Return human-readable warnings; raise on a differing source report unless allowed."""
    warnings: list[str] = []
    if baseline["report"] != arm["report"]:
        message = (
            "the two arms were replayed from DIFFERENT source reports, so their probe queries "
            f"differ:\n  baseline: {baseline['report']}\n  arm     : {arm['report']}\n"
            "Probe queries are an input. Pass --allow-different-reports only if varying them "
            "is the intervention being tested (e.g. a filtered copy of one report)."
        )
        if not allow:
            raise CompareReplayError(message)
        warnings.append("ALLOWED DIFFERENCE: " + message)
    if baseline["config"] != arm["config"]:
        warnings.append(f"configs differ: {baseline['config']} vs {arm['config']}")
    if baseline["candidate_limit"] != arm["candidate_limit"]:
        warnings.append(
            f"candidate_limit differs ({baseline['candidate_limit']} vs {arm['candidate_limit']}), "
            "which changes pool size and makes recall incomparable"
        )
    return warnings


def two_sided_sign_test(gained: int, lost: int) -> float:
    """Exact binomial p under p=0.5 on the discordant pairs only (McNemar, exact)."""
    total = gained + lost
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, k) for k in range(min(gained, lost) + 1))
    return min(1.0, 2 * tail / 2**total)


def compare(baseline: dict[str, Any], arm: dict[str, Any]) -> dict[str, Any]:
    base_cases = {case["case_id"]: case for case in baseline["per_case"]}
    arm_cases = {case["case_id"]: case for case in arm["per_case"]}
    shared = sorted(base_cases.keys() & arm_cases.keys())
    if not shared:
        raise CompareReplayError("the two arms share no case ids")
    only_base = sorted(base_cases.keys() - arm_cases.keys())
    only_arm = sorted(arm_cases.keys() - base_cases.keys())

    gained: list[tuple[str, str]] = []
    lost: list[tuple[str, str]] = []
    for case_id in shared:
        before = set(base_cases[case_id]["found"])
        after = set(arm_cases[case_id]["found"])
        gained.extend((case_id, path) for path in sorted(after - before))
        lost.extend((case_id, path) for path in sorted(before - after))
    return {
        "shared_cases": shared,
        "only_baseline": only_base,
        "only_arm": only_arm,
        "gained": gained,
        "lost": lost,
        "p_value": two_sided_sign_test(len(gained), len(lost)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("arm", type=Path)
    parser.add_argument(
        "--allow-different-reports",
        action="store_true",
        help="permit differing source reports, for arms that deliberately rewrite the probes",
    )
    args = parser.parse_args()

    baseline, arm = load(args.baseline), load(args.arm)
    for warning in check_provenance(baseline, arm, args.allow_different_reports):
        print(f"WARNING: {warning}\n")

    result = compare(baseline, arm)
    print(f"baseline {args.baseline}")
    print(f"  report {baseline['report']}")
    print(f"arm      {args.arm}")
    print(f"  report {arm['report']}")
    if result["only_baseline"] or result["only_arm"]:
        print(
            f"\ncases not shared -- baseline-only {result['only_baseline']}, "
            f"arm-only {result['only_arm']}"
        )
    print(f"\ncases compared: {len(result['shared_cases'])}")
    for metric in ("pool_recall_at_candidate_limit", "pool_bundle_complete"):
        before, after = baseline.get(metric), arm.get(metric)
        if before is None or after is None:
            continue
        print(f"  {metric:32} {before:.4f} -> {after:.4f}  ({after - before:+.4f})")

    gained, lost = result["gained"], result["lost"]
    print(f"\npaths gained {len(gained)}, lost {len(lost)}")
    print(f"exact sign test on {len(gained) + len(lost)} discordant paths: p = {result['p_value']:.3f}")
    for label, rows in (("gained", gained), ("lost", lost)):
        for case_id, path in rows:
            print(f"  {label:6} {case_id:34} {path}")


if __name__ == "__main__":
    main()
