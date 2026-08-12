"""Compares a candidate judge against a reference judge on the same cases.

Why this exists: the Gemini judge that scored every historical result is no longer
reachable, so a local model has to take over. Its raw scores are not interchangeable with
the saved ones -- a local 9B judge may be systematically generous, systematically harsh, or
simply noisy. Publishing its numbers next to the historical ones without checking would
silently rewrite the hypothesis ladder.

What actually matters is not agreement on absolute scores but agreement on ORDERING: the
judge's only job here is to say which setup is better. So the pooled per-case correlation is
reported alongside a system-level ranking check across reports, and the ranking check is the
one that decides whether the candidate can stand in for the reference.

Usage:
    compare_judges.py --pair reference.json candidate.json [--pair ref2.json cand2.json ...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import fmean, median
from typing import Any

# The six rubric criteria, compared individually. A raw sum of these (the historical "sum of
# criteria, max 24" metric) is never computed: it rewards citation-format density and suffers a
# judge halo effect, so agreement on it would not mean agreement on judgment quality.
JUDGE_CRITERIA: tuple[str, ...] = (
    "judge_answer_correctness",
    "judge_evidence_grounding",
    "judge_coverage",
    "judge_citation_quality",
    "judge_specificity",
    "judge_hallucination_control",
)


def load_scores(path: Path) -> dict[str, dict[str, float]]:
    """case_id -> {criterion: score}, keeping only cases the judge actually scored."""
    report = json.loads(path.read_text(encoding="utf-8"))
    scored: dict[str, dict[str, float]] = {}
    for row in report.get("results") or []:
        case_id = str(row.get("case_id") or "")
        scores = ((row.get("judge") or {}).get("scores")) or {}
        if not case_id or not scores:
            continue
        numeric = {key: float(value) for key, value in scores.items() if isinstance(value, (int, float))}
        if numeric:
            scored[case_id] = numeric
    return scored


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        # Ties share the average rank; judge scores are a 0-4 integer scale, so ties are the
        # common case and breaking them arbitrarily would inflate the correlation.
        shared = (position + end) / 2 + 1
        for index in range(position, end + 1):
            result[order[index]] = shared
        position = end + 1
    return result


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mean_x, mean_y = fmean(xs), fmean(ys)
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denominator = (sum(value * value for value in dx) * sum(value * value for value in dy)) ** 0.5
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / denominator


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return pearson(ranks(xs), ranks(ys))


def format_optional(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def compare_criterion(
    reference_scores: dict[str, dict[str, float]],
    candidate_scores: dict[str, dict[str, float]],
    shared: list[str],
    criterion: str,
) -> dict[str, Any]:
    """Per-criterion agreement: mean, bias (candidate - reference), MAD, and rank correlation."""
    paired = [
        (reference_scores[case][criterion], candidate_scores[case][criterion])
        for case in shared
        if criterion in reference_scores[case] and criterion in candidate_scores[case]
    ]
    if not paired:
        return {"cases": 0, "reference_mean": None, "candidate_mean": None, "bias": None, "mad": None, "spearman": None}
    reference_values = [pair[0] for pair in paired]
    candidate_values = [pair[1] for pair in paired]
    deltas = [c - r for r, c in paired]
    return {
        "cases": len(paired),
        "reference_mean": fmean(reference_values),
        "candidate_mean": fmean(candidate_values),
        "bias": fmean(deltas),
        "mad": fmean(abs(value) for value in deltas),
        "spearman": spearman(reference_values, candidate_values),
    }


def compare_abstention(
    reference_scores: dict[str, dict[str, float]],
    candidate_scores: dict[str, dict[str, float]],
    shared: list[str],
) -> dict[str, Any] | None:
    """Do the two judges agree on WHICH cases were abstentions? Older reports lack the key, so
    this returns None (skip silently) rather than crashing when either side never scored it."""
    paired = [
        (reference_scores[case]["judge_abstained"], candidate_scores[case]["judge_abstained"])
        for case in shared
        if "judge_abstained" in reference_scores[case] and "judge_abstained" in candidate_scores[case]
    ]
    if not paired:
        return None
    return {
        "cases": len(paired),
        "agreement_rate": sum(1 for r, c in paired if r == c) / len(paired),
        "reference_abstention_rate": sum(1 for r, _ in paired if r == 1.0) / len(paired),
        "candidate_abstention_rate": sum(1 for _, c in paired if c == 1.0) / len(paired),
        "both_abstained": sum(1 for r, c in paired if r == 1.0 and c == 1.0),
    }


def compare_pair(reference: Path, candidate: Path) -> dict[str, Any]:
    reference_scores, candidate_scores = load_scores(reference), load_scores(candidate)
    shared = sorted(set(reference_scores) & set(candidate_scores))
    overall_reference = [reference_scores[case].get("judge_overall", 0.0) for case in shared]
    overall_candidate = [candidate_scores[case].get("judge_overall", 0.0) for case in shared]
    deltas = [c - r for c, r in zip(overall_candidate, overall_reference, strict=True)]
    return {
        "reference": reference.name,
        "candidate": candidate.name,
        "reference_only": len(set(reference_scores) - set(candidate_scores)),
        "candidate_only": len(set(candidate_scores) - set(reference_scores)),
        "cases": len(shared),
        "overall_reference_mean": fmean(overall_reference) if shared else 0.0,
        "overall_candidate_mean": fmean(overall_candidate) if shared else 0.0,
        "bias": fmean(deltas) if deltas else 0.0,
        "mad": fmean([abs(value) for value in deltas]) if deltas else 0.0,
        "median_delta": median(deltas) if deltas else 0.0,
        "spearman_overall": spearman(overall_reference, overall_candidate),
        "pearson_overall": pearson(overall_reference, overall_candidate),
        "criteria": {
            criterion: compare_criterion(reference_scores, candidate_scores, shared, criterion)
            for criterion in JUDGE_CRITERIA
        },
        "abstention": compare_abstention(reference_scores, candidate_scores, shared),
        "overall_reference": overall_reference,
        "overall_candidate": overall_candidate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair",
        nargs=2,
        action="append",
        metavar=("REFERENCE", "CANDIDATE"),
        required=True,
        help="A reference-judged report and a candidate-judged report over the same cases.",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    comparisons = [compare_pair(Path(reference), Path(candidate)) for reference, candidate in args.pair]

    print(f"{'report':<34} {'n':>4} {'ref':>6} {'cand':>6} {'bias':>6} {'MAD':>6} {'rho':>6}  (judge_overall)")
    for row in comparisons:
        print(
            f"{row['candidate'][:34]:<34} {row['cases']:>4} "
            f"{row['overall_reference_mean']:>6.2f} {row['overall_candidate_mean']:>6.2f} "
            f"{row['bias']:>+6.2f} {row['mad']:>6.2f} "
            f"{format_optional(row['spearman_overall'], 2):>6}"
        )
        if row["reference_only"] or row["candidate_only"]:
            # Unscored cases are not random: a judge fails on the answers it finds hardest to
            # parse, so dropping them quietly flatters whichever judge failed more often.
            print(
                f"  {'':<32} scored only by reference: {row['reference_only']}, "
                f"only by candidate: {row['candidate_only']}"
            )
        print(f"  {'criterion':<28} {'n':>4} {'ref':>6} {'cand':>6} {'bias':>6} {'MAD':>6} {'rho':>6}")
        for criterion, stats in row["criteria"].items():
            if stats["cases"] == 0:
                print(f"    {criterion:<26} {'--':>4}")
                continue
            print(
                f"    {criterion:<26} {stats['cases']:>4} "
                f"{stats['reference_mean']:>6.2f} {stats['candidate_mean']:>6.2f} "
                f"{stats['bias']:>+6.2f} {stats['mad']:>6.2f} "
                f"{format_optional(stats['spearman'], 2):>6}"
            )
        abstention = row["abstention"]
        if abstention is not None:
            print(
                f"  judge_abstained agreement {abstention['agreement_rate']:.2f} "
                f"(n={abstention['cases']}, ref rate {abstention['reference_abstention_rate']:.2f}, "
                f"cand rate {abstention['candidate_abstention_rate']:.2f}, "
                f"both abstained {abstention['both_abstained']})"
            )

    pooled_reference = [value for row in comparisons for value in row["overall_reference"]]
    pooled_candidate = [value for row in comparisons for value in row["overall_candidate"]]
    print(f"\npooled cases: {len(pooled_reference)}")
    print(f"  spearman(overall)  {format_optional(spearman(pooled_reference, pooled_candidate))}")
    print(f"  pearson(overall)   {format_optional(pearson(pooled_reference, pooled_candidate))}")
    if pooled_reference:
        print(f"  bias (cand - ref)  {fmean(pooled_candidate) - fmean(pooled_reference):+.3f}")

    # The decision the judge is actually used for: does it order the systems the same way?
    if len(comparisons) >= 2:
        by_reference = sorted(comparisons, key=lambda row: row["overall_reference_mean"], reverse=True)
        by_candidate = sorted(comparisons, key=lambda row: row["overall_candidate_mean"], reverse=True)
        print("\nsystem ranking")
        print(f"  reference: {' > '.join(row['candidate'][:24] for row in by_reference)}")
        print(f"  candidate: {' > '.join(row['candidate'][:24] for row in by_candidate)}")
        reference_order = [row["candidate"] for row in by_reference]
        candidate_order = [row["candidate"] for row in by_candidate]
        if len(comparisons) >= 3:
            agreement = spearman(
                [float(reference_order.index(row["candidate"])) for row in comparisons],
                [float(candidate_order.index(row["candidate"])) for row in comparisons],
            )
            print(f"  rank agreement (spearman over systems): {format_optional(agreement)}")
        if reference_order == candidate_order:
            print("  -> identical ordering: the candidate can stand in for promotion decisions")
        else:
            print("  -> ORDERING DIFFERS: candidate scores are not a substitute for the reference")

    if args.json_out:
        payload = [{key: value for key, value in row.items() if not isinstance(value, list)} for row in comparisons]
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
