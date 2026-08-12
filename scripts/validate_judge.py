"""Measure agreement between human labels and the saved machine judge scores."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

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
DEFAULT_MIN_LABELLED = 10
ANSWER_TYPES = ("substantive", "abstention", "empty")
HALO_MARGIN = 0.15

# These are the weights used by the answer judge to derive its 0-5 overall score.  A human
# worksheet has no separate overall field, so a complete six-score row is normalised the same
# way unless a caller supplies human.judge_overall explicitly.
CRITERION_WEIGHTS = {
    "judge_answer_correctness": 0.30,
    "judge_evidence_grounding": 0.20,
    "judge_coverage": 0.15,
    "judge_citation_quality": 0.15,
    "judge_specificity": 0.10,
    "judge_hallucination_control": 0.10,
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def ranks(values: list[float]) -> list[float]:
    """Return one-based tie-averaged ranks."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
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


def _validate_score(value: Any, *, maximum: int, label: str, integer: bool = False) -> float:
    if not _is_number(value) or value < 0 or value > maximum or (integer and not float(value).is_integer()):
        bound = f"[{SCORE_MIN}, {maximum}]"
        kind = "integer " if integer else ""
        raise ValueError(f"{label} must be a {kind}number in {bound}, got {value!r}")
    return float(value)


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Load and minimally validate anchor rows, failing with a line number when needed."""
    rows: list[dict[str, Any]] = []
    try:
        handle = path.open(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read anchor JSONL {path}: {exc}") from exc
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number} is not valid JSON: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"line {line_number} must contain a JSON object")
            human = row.get("human")
            machine = row.get("machine_scores")
            if not isinstance(human, dict):
                raise ValueError(f"line {line_number} has no human object")
            if not isinstance(machine, dict):
                raise ValueError(f"line {line_number} has no machine_scores object")
            for criterion in CRITERIA:
                value = human.get(criterion)
                if value is not None:
                    _validate_score(value, maximum=SCORE_MAX, label=f"line {line_number} human.{criterion}", integer=True)
                machine_value = machine.get(criterion)
                if machine_value is not None:
                    _validate_score(machine_value, maximum=SCORE_MAX, label=f"line {line_number} machine.{criterion}")
            if human.get("judge_overall") is not None:
                _validate_score(human["judge_overall"], maximum=OVERALL_MAX, label=f"line {line_number} human.judge_overall")
            if machine.get("judge_overall") is not None:
                _validate_score(machine["judge_overall"], maximum=OVERALL_MAX, label=f"line {line_number} machine.judge_overall")
            answer_type = human.get("answer_type")
            if answer_type is not None and answer_type not in ANSWER_TYPES:
                raise ValueError(f"line {line_number} human.answer_type is invalid: {answer_type!r}")
            rows.append(row)
    return rows


def _human_overall(human: dict[str, Any]) -> float | None:
    explicit = human.get("judge_overall")
    if explicit is not None:
        return float(explicit)
    if any(human.get(criterion) is None for criterion in CRITERIA):
        return None
    weighted = sum(float(human[criterion]) * CRITERION_WEIGHTS[criterion] for criterion in CRITERIA)
    return weighted / SCORE_MAX * OVERALL_MAX


def _paired(rows: list[dict[str, Any]], criterion: str) -> tuple[list[float], list[float]]:
    human_values: list[float] = []
    machine_values: list[float] = []
    for row in rows:
        human = row["human"].get(criterion)
        machine = row["machine_scores"].get(criterion)
        if human is not None and machine is not None:
            human_values.append(float(human))
            machine_values.append(float(machine))
    return human_values, machine_values


def score_statistics(human: list[float], machine: list[float]) -> dict[str, Any]:
    """Calculate the scalar agreement statistics for one score column."""
    if not human:
        return {
            "n": 0,
            "human_mean": None,
            "machine_mean": None,
            "bias": None,
            "mad": None,
            "mean_absolute_deviation": None,
            "exact_agreement": None,
            "exact_agreement_rate": None,
            "within_1_agreement": None,
            "within_1_agreement_rate": None,
            "spearman": None,
            "spearman_rank_correlation": None,
        }
    deltas = [m - h for h, m in zip(human, machine, strict=True)]
    mad = fmean(abs(delta) for delta in deltas)
    exact = fmean(int(h == m) for h, m in zip(human, machine, strict=True))
    within_1 = fmean(int(abs(delta) <= 1) for delta in deltas)
    correlation = spearman(human, machine)
    return {
        "n": len(human),
        "human_mean": fmean(human),
        "machine_mean": fmean(machine),
        "bias": fmean(deltas),
        "mad": mad,
        "mean_absolute_deviation": mad,
        "exact_agreement": exact,
        "exact_agreement_rate": exact,
        "within_1_agreement": within_1,
        "within_1_agreement_rate": within_1,
        "spearman": correlation,
        "spearman_rank_correlation": correlation,
    }


def _answer_type(row: dict[str, Any]) -> str:
    machine = row["machine_scores"]
    value = machine.get("answer_type")
    if value in ANSWER_TYPES:
        return str(value)
    abstained = machine.get("judge_abstained")
    if isinstance(abstained, bool):
        return "abstention" if abstained else "substantive"
    return "unknown"


def answer_type_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    columns = (*ANSWER_TYPES, "unknown")
    matrix = {human_type: {machine_type: 0 for machine_type in columns} for human_type in ANSWER_TYPES}
    used = 0
    for row in rows:
        human_type = row["human"].get("answer_type")
        if human_type not in ANSWER_TYPES:
            continue
        matrix[human_type][_answer_type(row)] += 1
        used += 1
    unknown = sum(matrix[human_type]["unknown"] for human_type in ANSWER_TYPES)
    return {
        "n": used,
        "rows": list(ANSWER_TYPES),
        "columns": list(columns),
        "matrix": matrix,
        "unknown_machine_count": unknown,
        "note": "Machine answer type is unknown where machine_scores has neither answer_type nor judge_abstained."
        if unknown
        else "Machine answer type was available for every row with a human answer_type.",
    }


def halo_probe(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare mean pairwise criterion Spearman correlations for humans and machine."""
    human_correlations: list[float] = []
    machine_correlations: list[float] = []
    for position, left in enumerate(CRITERIA):
        for right in CRITERIA[position + 1 :]:
            # Each pair uses its own complete-case subset so partially labelled worksheets do
            # not silently turn a missing score into a zero.
            human_rows = [row for row in rows if row["human"].get(left) is not None and row["human"].get(right) is not None]
            machine_rows = [
                row
                for row in rows
                if row["machine_scores"].get(left) is not None and row["machine_scores"].get(right) is not None
            ]
            human_rho = spearman(
                [float(row["human"][left]) for row in human_rows],
                [float(row["human"][right]) for row in human_rows],
            )
            machine_rho = spearman(
                [float(row["machine_scores"][left]) for row in machine_rows],
                [float(row["machine_scores"][right]) for row in machine_rows],
            )
            if human_rho is not None:
                human_correlations.append(human_rho)
            if machine_rho is not None:
                machine_correlations.append(machine_rho)
    human_mean = fmean(human_correlations) if human_correlations else None
    machine_mean = fmean(machine_correlations) if machine_correlations else None
    fires = machine_mean is not None and human_mean is not None and machine_mean >= human_mean + HALO_MARGIN
    if fires:
        verdict = (
            f"HALO-EFFECT PROBE FIRES: machine mean inter-criterion Spearman {machine_mean:.3f} "
            f"vs human {human_mean:.3f} (margin {HALO_MARGIN:.2f})."
        )
    else:
        verdict = (
            f"HALO-EFFECT PROBE: no marked collapse (machine mean {machine_mean if machine_mean is not None else 'n/a'}, "
            f"human mean {human_mean if human_mean is not None else 'n/a'})."
        )
    return {
        "human_mean_intercriterion_spearman": human_mean,
        "machine_mean_intercriterion_spearman": machine_mean,
        "human_pair_count": len(human_correlations),
        "machine_pair_count": len(machine_correlations),
        "margin": HALO_MARGIN,
        "fires": fires,
        "verdict": verdict,
    }


def validate_rows(rows: list[dict[str, Any]], min_labelled: int = DEFAULT_MIN_LABELLED) -> dict[str, Any]:
    """Build the complete validation payload from loaded anchor rows."""
    labelled = [row for row in rows if any(row["human"].get(criterion) is not None for criterion in CRITERIA)]
    if len(labelled) < min_labelled:
        raise ValueError(f"only {len(labelled)} labelled rows found; need at least {min_labelled}")
    criteria: dict[str, Any] = {}
    for criterion in (*CRITERIA, "judge_overall"):
        if criterion == "judge_overall":
            human_values: list[float] = []
            machine_values: list[float] = []
            for row in labelled:
                human = _human_overall(row["human"])
                machine = row["machine_scores"].get(criterion)
                if human is not None and machine is not None:
                    human_values.append(human)
                    machine_values.append(float(machine))
        else:
            human_values, machine_values = _paired(labelled, criterion)
        criteria[criterion] = score_statistics(human_values, machine_values)
    return {
        "labelled_rows": len(labelled),
        "criteria": criteria,
        "answer_type": answer_type_matrix(labelled),
        "halo_effect_probe": halo_probe(labelled),
    }


def _format(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _format_signed(value: Any, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def print_report(report: dict[str, Any]) -> None:
    print(f"labelled rows: {report['labelled_rows']}")
    print("\nscore agreement")
    print(f"{'criterion':<34} {'n':>4} {'human':>7} {'machine':>7} {'bias':>7} {'MAD':>7} {'exact':>7} {'within1':>8} {'rho':>7}")
    for criterion, values in report["criteria"].items():
        print(
            f"{criterion:<34} {values['n']:>4} {_format(values['human_mean']):>7} "
            f"{_format(values['machine_mean']):>7} {_format_signed(values['bias']):>7} "
            f"{_format(values['mean_absolute_deviation']):>7} {_format(values['exact_agreement_rate']):>7} "
            f"{_format(values['within_1_agreement_rate']):>8} {_format(values['spearman_rank_correlation']):>7}"
        )
    answer = report["answer_type"]
    print("\nanswer_type confusion matrix (human rows, machine columns)")
    print(f"{'human \\ machine':<18} {'substantive':>12} {'abstention':>12} {'empty':>12} {'unknown':>12}")
    for human_type in answer["rows"]:
        print(f"{human_type:<18}" + "".join(f"{answer['matrix'][human_type][machine_type]:>12}" for machine_type in answer["columns"]))
    print(f"  {answer['note']}")
    print(f"\n{report['halo_effect_probe']['verdict']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("anchor_jsonl", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--min-labelled", type=int, default=DEFAULT_MIN_LABELLED)
    args = parser.parse_args()
    if args.min_labelled < 0:
        parser.error("--min-labelled must be non-negative")
    try:
        report = validate_rows(load_rows(args.anchor_jsonl), args.min_labelled)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print_report(report)
    if args.json_out:
        try:
            args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write {args.json_out}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
