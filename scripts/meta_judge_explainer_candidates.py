from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any

from code_diver.config import ConfigLoader
from code_diver.explanation import ExplanationDatasetLoader
from code_diver.explanation.explanation_judge_rubric import ExplanationJudgeRubric
from code_diver.explanation.jsonish_parser import JsonishParser
from code_diver.generation import create_generation_provider


SLOTS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def main() -> int:
    args = parse_args()
    cases = ExplanationDatasetLoader().load(args.dataset)
    if args.cases:
        cases = cases[: args.cases]
    candidates = load_candidates(args.candidate, allow_partial=args.allow_partial)
    provider = create_generation_provider(ConfigLoader().load(args.judge_config))
    rubric = ExplanationJudgeRubric()
    parser = JsonishParser()
    permutations = balanced_permutations(
        labels=[candidate["label"] for candidate in candidates],
        total=len(cases),
        seed=args.seed,
    )

    rows_by_index: list[dict[str, Any] | None] = [None] * len(cases)
    completed = 0
    usage = empty_usage()
    judge_errors = 0
    started = perf_counter()

    def run_case(index: int) -> dict[str, Any]:
        case = cases[index]
        permutation = permutations[index]
        return judge_case(
            case=case,
            candidates=candidates,
            permutation=permutation,
            provider=provider,
            rubric=rubric,
            parser=parser,
        )

    worker_count = max(1, int(args.workers or 1))
    if worker_count == 1:
        for index in range(len(cases)):
            row = run_case(index)
            rows_by_index[index] = row
            completed += 1
            merge_usage(usage, row.get("usage"))
            judge_errors += int(bool(row.get("judge_error")))
            write_partial(args.partial_output, args.output, rows_by_index, completed, usage, judge_errors)
            print(f"meta-judged {completed}/{len(cases)} {row['case_id']}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(run_case, index): index for index in range(len(cases))}
            for future in as_completed(futures):
                index = futures[future]
                row = future.result()
                rows_by_index[index] = row
                completed += 1
                merge_usage(usage, row.get("usage"))
                judge_errors += int(bool(row.get("judge_error")))
                write_partial(args.partial_output, args.output, rows_by_index, completed, usage, judge_errors)
                print(f"meta-judged {completed}/{len(cases)} {row['case_id']}", flush=True)

    rows = [row for row in rows_by_index if row is not None]
    payload = {
        "dataset": str(args.dataset),
        "judge_config": str(args.judge_config),
        "judge_model": getattr(provider, "model", None),
        "seed": args.seed,
        "candidate_reports": [
            {"label": candidate["label"], "path": str(candidate["path"])}
            for candidate in candidates
        ],
        "position_counts": position_counts(rows),
        "summary": summarize(rows, [candidate["label"] for candidate in candidates], args.bootstrap_samples),
        "usage": usage,
        "judge_error_count": judge_errors,
        "duration_ms": (perf_counter() - started) * 1000,
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.markdown:
        print(markdown_summary(payload))
    else:
        print(f"saved meta judge report: {args.output}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Blind listwise meta-judge for code explainer candidates.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--judge-config", type=Path, required=True)
    parser.add_argument("--candidate", action="append", required=True, help="Candidate as label=report.json")
    parser.add_argument("--cases", type=int, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partial-output", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args()


def load_candidates(values: list[str], allow_partial: bool = False) -> list[dict[str, Any]]:
    candidates = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Candidate must be label=path: {value}")
        label, raw_path = value.split("=", 1)
        label = label.strip()
        path = Path(raw_path.strip())
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("partial") and not allow_partial:
            raise ValueError(f"Refusing partial candidate report without --allow-partial: {path}")
        rows = {
            str(row.get("case_id")): row
            for row in payload.get("results") or []
            if isinstance(row, dict)
        }
        candidates.append({"label": label, "path": path, "payload": payload, "rows": rows})
    if len(candidates) > len(SLOTS):
        raise ValueError(f"Too many candidates: max {len(SLOTS)}")
    return candidates


def balanced_permutations(labels: list[str], total: int, seed: int) -> list[list[str]]:
    rng = random.Random(seed)
    counts: dict[str, Counter[int]] = {label: Counter() for label in labels}
    permutations: list[list[str]] = []
    for _ in range(total):
        best: list[str] | None = None
        best_score: tuple[int, float] | None = None
        for _attempt in range(256):
            candidate = list(labels)
            rng.shuffle(candidate)
            score = position_imbalance(counts, candidate) + rng.random() * 1e-6
            score_key = (score, rng.random())
            if best_score is None or score_key < best_score:
                best = candidate
                best_score = score_key
        assert best is not None
        for position, label in enumerate(best):
            counts[label][position] += 1
        permutations.append(best)
    return permutations


def position_imbalance(counts: dict[str, Counter[int]], permutation: list[str]) -> int:
    updated = {label: Counter(counter) for label, counter in counts.items()}
    for position, label in enumerate(permutation):
        updated[label][position] += 1
    return sum(count * count for counter in updated.values() for count in counter.values())


def judge_case(
    *,
    case: Any,
    candidates: list[dict[str, Any]],
    permutation: list[str],
    provider: Any,
    rubric: ExplanationJudgeRubric,
    parser: JsonishParser,
) -> dict[str, Any]:
    label_to_candidate = {candidate["label"]: candidate for candidate in candidates}
    slot_items = []
    for slot_index, label in enumerate(permutation):
        candidate = label_to_candidate[label]
        row = candidate["rows"].get(case.id)
        missing_from_report = row is None
        if row is None:
            row = {}
        prediction = str(row.get("prediction") or "").strip()
        if not prediction:
            prediction = "[NO VALID EXPLANATION RETURNED]"
        slot_items.append(
            {
                "slot": SLOTS[slot_index],
                "label": label,
                "path": str(candidate["path"]),
                "prediction": prediction,
                "source_error": row.get("error"),
                "missing_from_report": missing_from_report,
            }
        )
    prompt = build_prompt(case, slot_items)
    started = perf_counter()
    try:
        result = provider.generate_json_result(prompt)
        parsed = parser.parse_object(result.text)
        scores = score_meta_response(parsed, slot_items, rubric)
        return {
            "case_id": case.id,
            "metadata": case.metadata,
            "permutation": [
                {
                    "slot": item["slot"],
                    "candidate": item["label"],
                    "source_report": item["path"],
                    "source_error": item["source_error"],
                    "missing_from_report": item["missing_from_report"],
                }
                for item in slot_items
            ],
            "scores": scores,
            "raw_judge": parsed,
            "usage": {
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
            "duration_ms": (perf_counter() - started) * 1000,
        }
    except Exception as exc:
        return {
            "case_id": case.id,
            "metadata": case.metadata,
            "permutation": [
                {
                    "slot": item["slot"],
                    "candidate": item["label"],
                    "source_report": item["path"],
                    "source_error": item["source_error"],
                    "missing_from_report": item["missing_from_report"],
                }
                for item in slot_items
            ],
            "scores": {},
            "judge_error": str(exc),
            "duration_ms": (perf_counter() - started) * 1000,
        }


def build_prompt(case: Any, slot_items: list[dict[str, Any]]) -> str:
    candidate_blocks = "\n\n".join(
        f"Candidate {item['slot']}:\n{item['prediction']}" for item in slot_items
    )
    slots = ", ".join(item["slot"] for item in slot_items)
    return f"""You are comparing developer-facing code explanations.

Use the source code as the primary truth. Use the reference answer/docstring as
supporting truth, but do not require identical wording.

Candidate order is randomized and candidate IDs are anonymous. Do not prefer an
answer because of its position. Penalize empty or invalid answers.

For each candidate ({slots}), score each criterion from 0 to 4:

- 4: excellent; materially correct and useful.
- 3: mostly correct; minor omissions or imprecision.
- 2: partially correct; important omissions or some vague/unsupported claims.
- 1: mostly wrong; small useful fragment, but major misunderstanding.
- 0: wrong, empty, unsafe, or hallucinated.

Return JSON only — for each candidate score each criterion from 0 to 4, with
evidence:

{{
  "candidates": {{
    "A": {{
      "criteria": {{
        "purpose_accuracy": {{"score": 0, "evidence": "brief reason"}},
        "behavior_accuracy": {{"score": 0, "evidence": "brief reason"}},
        "api_contract": {{"score": 0, "evidence": "brief reason"}},
        "groundedness": {{"score": 0, "evidence": "brief reason"}},
        "specificity": {{"score": 0, "evidence": "brief reason"}},
        "completeness": {{"score": 0, "evidence": "brief reason"}},
        "clarity": {{"score": 0, "evidence": "brief reason"}}
      }},
      "summary": "brief reason for this candidate's placement"
    }}
  }}
}}

User prompt:
{case.prompt}

Function metadata:
{json.dumps(case.metadata, ensure_ascii=False, indent=2)}

Code:
```python
{case.code}
```

Reference answer/docstring:
{case.reference}

Candidate explanations:
{candidate_blocks}
"""


def score_meta_response(
    payload: dict[str, Any],
    slot_items: list[dict[str, Any]],
    rubric: ExplanationJudgeRubric,
) -> dict[str, Any]:
    candidates_payload = payload.get("candidates")
    if not isinstance(candidates_payload, dict):
        candidates_payload = {}
    scores = {}
    for item in slot_items:
        slot = item["slot"]
        candidate_payload = candidates_payload.get(slot)
        if not isinstance(candidate_payload, dict):
            candidate_payload = {}
        scored = rubric.score(candidate_payload)
        scores[item["label"]] = {
            "slot": slot,
            "judge_overall": scored["scores"]["judge_overall"],
            "scores": scored["scores"],
            "questionnaire": scored["questionnaire"],
            "summary": str(candidate_payload.get("summary") or "").strip(),
        }
    return scores



def summarize(rows: list[dict[str, Any]], labels: list[str], bootstrap_samples: int) -> dict[str, Any]:
    summary = {}
    for label in labels:
        scored_rows = [
            row["scores"][label]
            for row in rows
            if isinstance(row.get("scores"), dict) and label in row["scores"]
        ]
        overalls = [float(item["judge_overall"]) for item in scored_rows]
        score_distributions = summarize_score_distributions(scored_rows, bootstrap_samples)
        summary[label] = {
            "cases": len(scored_rows),
            "mean_judge_overall": mean(overalls) if overalls else 0.0,
            "median_judge_overall": median(overalls) if overalls else 0.0,
            "median_judge_overall_ci95": bootstrap_median_ci(overalls, bootstrap_samples),
            "score_distributions": score_distributions,
        }
    return summary


def summarize_score_distributions(scored_rows: list[dict[str, Any]], bootstrap_samples: int) -> dict[str, Any]:
    keys = sorted(
        {
            key
            for item in scored_rows
            for key in (item.get("scores") or {})
            if str(key).startswith("judge_")
        }
    )
    distributions = {}
    for key in keys:
        values = [float((item.get("scores") or {}).get(key) or 0.0) for item in scored_rows]
        distributions[key] = {
            "mean": mean(values) if values else 0.0,
            "median": median(values) if values else 0.0,
            "median_ci95": bootstrap_median_ci(values, bootstrap_samples),
        }
    return distributions


def bootstrap_median_ci(values: list[float], samples: int) -> dict[str, float]:
    if not values:
        return {"low": 0.0, "high": 0.0}
    if len(values) <= 1 or samples <= 0:
        value = median(values)
        return {"low": value, "high": value}
    rng = random.Random(17)
    n = len(values)
    estimates = []
    for _ in range(samples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        estimates.append(median(sample))
    estimates.sort()
    low_index = int(0.025 * (len(estimates) - 1))
    high_index = int(0.975 * (len(estimates) - 1))
    return {"low": estimates[low_index], "high": estimates[high_index]}


def position_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for item in row.get("permutation") or []:
            counts[str(item["candidate"])][str(item["slot"])] += 1
    return {candidate: dict(counter) for candidate, counter in counts.items()}


def empty_usage() -> dict[str, Any]:
    return {
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "models": [],
    }


def merge_usage(target: dict[str, Any], usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    target["model_calls"] += 1
    target["input_tokens"] += int(usage.get("input_tokens") or 0)
    target["output_tokens"] += int(usage.get("output_tokens") or 0)
    target["total_tokens"] += int(usage.get("total_tokens") or 0)
    model = usage.get("model")
    if model and model not in target["models"]:
        target["models"].append(model)


def write_partial(
    partial_output: Path | None,
    output: Path,
    rows_by_index: list[dict[str, Any] | None],
    completed: int,
    usage: dict[str, Any],
    judge_errors: int,
) -> None:
    if partial_output is None:
        return
    partial_output.parent.mkdir(parents=True, exist_ok=True)
    partial_output.write_text(
        json.dumps(
            {
                "partial": True,
                "completed": completed,
                "total": len(rows_by_index),
                "output": str(output),
                "usage": usage,
                "judge_error_count": judge_errors,
                "results": [row for row in rows_by_index if row is not None],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def markdown_summary(payload: dict[str, Any]) -> str:
    lines = [
        "| Candidate | Cases | Mean overall | Total sum | Median overall | Overall median 95% CI |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for label, row in sorted(payload["summary"].items(), key=lambda item: -item[1]["mean_judge_overall"]):
        overall_ci = row["median_judge_overall_ci95"]
        total_sum = row["mean_judge_overall"] * row["cases"]
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(row["cases"]),
                    f"{row['mean_judge_overall']:.3f}",
                    f"{total_sum:.1f}",
                    f"{row['median_judge_overall']:.3f}",
                    f"{overall_ci['low']:.3f}..{overall_ci['high']:.3f}",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
