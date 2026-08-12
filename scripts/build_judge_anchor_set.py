"""Build a stratified, machine-score-blind worksheet for judge validation.

The worksheet deliberately keeps the saved machine scores in JSONL only.  The optional
Markdown rendering is intended for a person to label without seeing those scores.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, TextIO

CRITERIA = (
    "judge_answer_correctness",
    "judge_evidence_grounding",
    "judge_coverage",
    "judge_citation_quality",
    "judge_specificity",
    "judge_hallucination_control",
)
SCORE_MIN = 0
SCORE_MAX = 4
OVERALL_MIN = 0
OVERALL_MAX = 5
DEFAULT_SIZE = 30
DEFAULT_SEED = 0
TERCILES = ("low", "mid", "high")
CONTEXT_LABELS = ("incomplete", "complete")
ANSWER_TYPES = ("substantive", "abstention", "empty")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _score(value: Any, *, maximum: int, label: str) -> int | float:
    if not _is_number(value) or value < 0 or value > maximum:
        raise ValueError(f"{label} must be a number in [{SCORE_MIN}, {maximum}], got {value!r}")
    if float(value).is_integer():
        return int(value)
    return float(value)


def _context_complete(row: dict[str, Any]) -> bool:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError(f"case {row.get('case_id')!r} has no metrics object")
    value = metrics.get("context_bundle_complete")
    if not _is_number(value) or value not in (0, 1):
        raise ValueError(
            f"case {row.get('case_id')!r} has invalid metrics.context_bundle_complete: {value!r}"
        )
    return bool(value)


def _judge_scores(row: dict[str, Any]) -> dict[str, int | float] | None:
    judge = row.get("judge")
    if judge is None:
        return None
    if not isinstance(judge, dict):
        raise ValueError(f"case {row.get('case_id')!r} has a non-object judge block")
    scores = judge.get("scores")
    if not isinstance(scores, dict) or not scores:
        return None
    result: dict[str, int | float] = {}
    for criterion in CRITERIA:
        if criterion not in scores:
            raise ValueError(f"case {row.get('case_id')!r} judge.scores is missing {criterion}")
        result[criterion] = _score(scores[criterion], maximum=SCORE_MAX, label=f"{criterion} for case {row.get('case_id')!r}")
    if "judge_overall" not in scores:
        raise ValueError(f"case {row.get('case_id')!r} judge.scores is missing judge_overall")
    result["judge_overall"] = _score(
        scores["judge_overall"], maximum=OVERALL_MAX, label=f"judge_overall for case {row.get('case_id')!r}"
    )
    return result


def _tercile(position: int, count: int) -> str:
    return TERCILES[min(len(TERCILES) - 1, position * len(TERCILES) // count)]


def _stratum_label(tercile: str | None, complete: bool) -> str:
    context = "complete" if complete else "incomplete"
    return f"{tercile + '/' if tercile else ''}{context}"


def _machine_scores(row: dict[str, Any], scores: dict[str, int | float] | None) -> dict[str, Any]:
    machine: dict[str, Any] = {criterion: (scores.get(criterion) if scores else None) for criterion in CRITERIA}
    machine["judge_overall"] = scores.get("judge_overall") if scores else None

    # Newer reports may carry the judge's answer type; old reports do not.  Preserve these
    # optional fields so validate_judge can measure answer-type agreement when available.
    judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
    answer_type = judge.get("answer_type", row.get("answer_type"))
    if answer_type in ANSWER_TYPES:
        machine["answer_type"] = answer_type
    abstained = judge.get("judge_abstained", row.get("judge_abstained"))
    if isinstance(abstained, bool):
        machine["judge_abstained"] = abstained
    return machine


def _worksheet_row(
    row: dict[str, Any],
    source_report: str,
    stratum: str,
    scores: dict[str, int | float] | None,
) -> dict[str, Any]:
    case_id = row.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError(f"result has invalid case_id: {case_id!r}")
    complete = _context_complete(row)
    return {
        "case_id": case_id,
        "question": row.get("question", ""),
        "reference": row.get("reference", ""),
        "prediction": row.get("prediction", ""),
        "expected_paths": row.get("expected_paths", []),
        "citations": row.get("citations", []),
        "context_bundle_complete": complete,
        "source_report": source_report,
        "stratum": stratum,
        "machine_scores": _machine_scores(row, scores),
        "human": {criterion: None for criterion in CRITERIA}
        | {"answer_type": None, "notes": ""},
    }


def allocate_counts(strata: dict[str, list[dict[str, Any]]], size: int) -> dict[str, int]:
    """Allocate a sample proportionally, distributing rounding remainder round-robin."""
    if size < 0:
        raise ValueError("size must be non-negative")
    total = sum(len(rows) for rows in strata.values())
    target = min(size, total)
    non_empty = [label for label, rows in strata.items() if rows]
    counts = {label: 0 for label in strata}
    if not total or not target:
        return counts
    for label in non_empty:
        counts[label] = target * len(strata[label]) // total
    remainder = target - sum(counts.values())
    position = 0
    while remainder:
        label = non_empty[position % len(non_empty)]
        if counts[label] < len(strata[label]):
            counts[label] += 1
            remainder -= 1
        position += 1
    return counts


def build_anchor_rows(
    report: dict[str, Any], source_report: str, size: int = DEFAULT_SIZE, seed: int = DEFAULT_SEED
) -> tuple[list[dict[str, Any]], dict[str, int], bool]:
    """Return sampled worksheet rows, realised counts, and whether fallback was used."""
    raw_rows = report.get("results")
    if not isinstance(raw_rows, list):
        raise ValueError("report.results must be an array")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("size must be a non-negative integer")

    parsed: list[tuple[dict[str, Any], dict[str, int | float] | None]] = []
    seen: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            raise ValueError("each report.results entry must be an object")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"result has invalid case_id: {case_id!r}")
        if case_id in seen:
            raise ValueError(f"duplicate case_id in report.results: {case_id!r}")
        seen.add(case_id)
        scores = _judge_scores(row)
        parsed.append((row, scores))

    has_judges = any(scores is not None for _, scores in parsed)
    if has_judges:
        eligible = [(row, scores) for row, scores in parsed if scores is not None]
        ignored = len(parsed) - len(eligible)
        if ignored:
            print(f"ignored {ignored} result(s) without a judge block", file=sys.stderr)
    else:
        eligible = parsed
        print("no judge blocks found; falling back to context_bundle_complete strata", file=sys.stderr)

    strata: dict[str, list[tuple[dict[str, Any], dict[str, int | float] | None]]] = {}
    if has_judges:
        ranked = sorted(
            ((row, scores) for row, scores in eligible),
            key=lambda item: (float(item[1]["judge_overall"]), item[0]["case_id"]),  # type: ignore[index]
        )
        for position, (row, scores) in enumerate(ranked):
            label = _stratum_label(_tercile(position, len(ranked)), _context_complete(row))
            strata.setdefault(label, []).append((row, scores))
    else:
        for row, scores in eligible:
            label = _stratum_label(None, _context_complete(row))
            strata.setdefault(label, []).append((row, scores))

    # A fixed ordering makes both the allocation remainder and RNG consumption reproducible.
    ordered_strata = {label: strata[label] for label in sorted(strata)}
    counts = allocate_counts(ordered_strata, size)
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    realised: dict[str, int] = {}
    for label, entries in ordered_strata.items():
        entries = sorted(entries, key=lambda item: item[0]["case_id"])
        chosen = rng.sample(entries, counts[label])
        realised[label] = len(chosen)
        selected.extend(_worksheet_row(row, source_report, label, scores) for row, scores in chosen)
    for label in sorted(realised):
        print(f"stratum {label}: {realised[label]}", file=sys.stderr)
    return selected, realised, not has_judges


def render_markdown(rows: list[dict[str, Any]]) -> str:
    """Render the human worksheet without copying any machine score values."""
    lines = [
        "# Human anchor worksheet",
        "",
        "Score each criterion from 0 to 4: 4 = flawless, 3 = minor issues, "
        "2 = partial, 1 = mostly wrong, 0 = empty/wrong/hallucinated.",
        "Use `answer_type`: `substantive`, `abstention`, or `empty`.",
        "",
    ]
    for number, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"## {number}. {row['case_id']}",
                "",
                "### Question",
                "",
                str(row["question"]),
                "",
                "### Expected paths",
                "",
                f"```json\n{json.dumps(row['expected_paths'], ensure_ascii=False, indent=2)}\n```",
                "",
                "### Reference answer",
                "",
                str(row["reference"]),
                "",
                "### Model prediction",
                "",
                str(row["prediction"]),
                "",
                "### Human scoring",
                "",
            ]
        )
        lines.extend(f"- {criterion}: __ / {SCORE_MAX}" for criterion in CRITERIA)
        lines.extend(["- answer_type: __ (substantive / abstention / empty)", "- notes: ", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, default=None)
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("report JSON must contain an object at the top level")
        rows, _, _ = build_anchor_rows(report, str(args.report), args.size, args.seed)
        args.output_jsonl.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        if args.output_markdown:
            args.output_markdown.write_text(render_markdown(rows), encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
