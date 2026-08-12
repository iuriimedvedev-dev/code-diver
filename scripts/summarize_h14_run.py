"""Prints one H14 run as a promotion decision, not as a metric dump.

The deterministic block comes first and is the primary signal: it is computed from the
dataset's expected paths and the context bundle, so no model -- least of all a small local
judge grading its own family -- can inflate it. The judge block is printed second and
labelled secondary, because until the local judge is validated against the saved Gemini
strict-judge scores its numbers are not comparable to the historical ones.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Primary: deterministic, model-free. `context_bundle_complete` leads -- 1.0 only when every
# expected file made it into the context bundle, so it is the actual bottleneck for a small
# local model. `answer_grounded` is the gate right behind it -- answered, cited, every citation
# resolvable in the context, at least one citation on an expected file.
PRIMARY_METRICS = (
    "context_bundle_complete",
    "answer_grounded",
    "answer_nonempty",
    "citation_expected_hit",
    "citation_expected_recall",
    "citation_expected_precision",
    "citation_fabricated_rate",
    "context_file_hit",
    "file_hit",
    "candidate_file_hit@1",
    "citation_path_valid_rate",
)
# Judge criteria, printed individually (never summed -- a raw sum of the six rewards
# citation-format density and suffers a judge halo effect: see PRIMARY_METRICS docstring
# above). `judge_abstained` is the abstention rate, `judge_overall` is a weighted mean.
JUDGE_CRITERIA = (
    "judge_answer_correctness",
    "judge_evidence_grounding",
    "judge_coverage",
    "judge_citation_quality",
    "judge_specificity",
    "judge_hallucination_control",
)
# Secondary: reference-overlap. Cheap and model-free, but a fabrication that reuses the
# reference's vocabulary scores well here, which is why it is not the gate.
OVERLAP_METRICS = ("token_f1", "key_token_f1", "bigram_f1")
COST_METRICS = ("answer_duration_ms_mean", "retrieval_duration_ms", "generation_duration_ms")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_metric(metrics: dict[str, Any], key: str) -> str:
    value = metrics.get(key)
    if value is None:
        return f"  {key:<32} --"
    low, high = metrics.get(f"{key}_ci95_low"), metrics.get(f"{key}_ci95_high")
    interval = f"  [{low:.3f}, {high:.3f}]" if isinstance(low, (int, float)) and isinstance(high, (int, float)) else ""
    return f"  {key:<32} {float(value):.3f}{interval}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--judge-report", type=Path, default=None)
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    if not args.report.exists():
        print(f"No report at {args.report} -- the evaluation did not produce output.")
        return 1
    report = load(args.report)
    metrics = report.get("metrics") or {}
    rows = report.get("results") or []
    errors = [row for row in rows if row.get("error")]

    print(f"\n=== {args.label or args.report.stem} ===")
    print(f"  cases {len(rows)}, errors {len(errors)}")
    if errors:
        # Errors are infrastructure, not model quality, and they drag every mean down. Naming
        # them here keeps a broken run from being read as a weak model.
        first = str(errors[0].get("error"))[:160]
        print(f"  first error: {first}")

    print("\n-- deterministic (PRIMARY) --")
    for key in PRIMARY_METRICS:
        print(format_metric(metrics, key))
    print("\n-- reference overlap --")
    for key in OVERLAP_METRICS:
        print(format_metric(metrics, key))
    print("\n-- cost --")
    for key in COST_METRICS:
        value = metrics.get(key)
        print(f"  {key:<32} {float(value):.0f} ms" if isinstance(value, (int, float)) else f"  {key:<32} --")

    if args.judge_report and args.judge_report.exists():
        judge_metrics = load(args.judge_report).get("metrics") or {}
        print(f"\n-- local judge (SECONDARY, unvalidated: {args.judge_report.name}) --")
        for key in JUDGE_CRITERIA:
            print(format_metric(judge_metrics, key))
        if "judge_abstained" in judge_metrics:
            print(format_metric(judge_metrics, "judge_abstained"))
        overall = judge_metrics.get("judge_overall")
        if isinstance(overall, (int, float)):
            print(f"  {'judge_overall (max 5, de-emphasised)':<38} {float(overall):.2f}")
    else:
        print("\n-- local judge: not run --")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
