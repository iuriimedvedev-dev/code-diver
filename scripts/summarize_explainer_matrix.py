from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from statistics import mean, median
from typing import Any


JUDGE_KEYS = [
    "judge_overall",
    "judge_purpose_accuracy",
    "judge_behavior_accuracy",
    "judge_api_contract",
    "judge_groundedness",
    "judge_specificity",
    "judge_completeness",
    "judge_clarity",
]

OVERLAP_KEYS = ["token_f1", "key_token_f1", "bigram_f1"]


def main() -> int:
    args = parse_args()
    rows = [summarize_report(path, args.bootstrap_samples) for path in args.reports]
    payload = {"reports": rows}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.markdown:
        print(markdown_table(rows))
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize code explainer reports with median and bootstrap CIs.")
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args()


def summarize_report(path: Path, bootstrap_samples: int) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in payload.get("results") or [] if isinstance(row, dict)]
    metrics = payload.get("metrics") or {}
    candidate = _candidate_name(payload, path)
    values = {key: metric_values(rows, key) for key in [*JUDGE_KEYS, *OVERLAP_KEYS]}
    empty_explanations = sum(
        1
        for row in rows
        if not str(row.get("prediction") or "").strip() and not row.get("error")
    )
    generation_errors = int(payload.get("error_count") or sum(1 for row in rows if row.get("error")))
    summary: dict[str, Any] = {
        "candidate": candidate,
        "path": str(path),
        "source_report": payload.get("source_report"),
        "cases": len(rows),
        "valid_explanations": sum(1 for row in rows if str(row.get("prediction") or "").strip() and not row.get("error")),
        "generation_errors": generation_errors,
        "empty_explanations": empty_explanations,
        "invalid_explanations": generation_errors + empty_explanations,
        "judge_errors": int(payload.get("judge_error_count") or sum(1 for row in rows if row.get("judge_error"))),
        "judge_calls": int((payload.get("judge_usage") or {}).get("model_calls") or 0),
        "judge": (payload.get("judge") or {}).get("model"),
        "mean_prediction_tokens": float(metrics.get("prediction_tokens") or 0.0),
    }
    for key, series in values.items():
        summary[key] = distribution_summary(series, bootstrap_samples)
    return summary


def metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        values.append(float(metrics.get(key) or 0.0))
    return values


def distribution_summary(values: list[float], bootstrap_samples: int) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    return {
        "mean": mean(values),
        "median": median(values),
        **bootstrap_ci(values, bootstrap_samples),
    }


def bootstrap_ci(values: list[float], samples: int) -> dict[str, float]:
    if len(values) <= 1 or samples <= 0:
        value = mean(values) if values else 0.0
        return {"ci95_low": value, "ci95_high": value}
    rng = random.Random(17)
    n = len(values)
    estimates = []
    for _ in range(samples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        estimates.append(median(sample))
    estimates.sort()
    low_index = int(0.025 * (len(estimates) - 1))
    high_index = int(0.975 * (len(estimates) - 1))
    return {"ci95_low": estimates[low_index], "ci95_high": estimates[high_index]}


def markdown_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Candidate | Cases | Valid | Gen errors | Empty | Invalid | Judge errors | Judge calls | Overall mean | Overall median | Overall median 95% CI | Token F1 median | Key F1 median | Bigram F1 median |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        overall = row["judge_overall"]
        token = row["token_f1"]
        key = row["key_token_f1"]
        bigram = row["bigram_f1"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["candidate"]),
                    str(row["cases"]),
                    str(row["valid_explanations"]),
                    str(row["generation_errors"]),
                    str(row["empty_explanations"]),
                    str(row["invalid_explanations"]),
                    str(row["judge_errors"]),
                    str(row["judge_calls"]),
                    f"{overall['mean']:.3f}",
                    f"{overall['median']:.3f}",
                    f"{overall['ci95_low']:.3f}..{overall['ci95_high']:.3f}",
                    f"{token['median']:.3f}",
                    f"{key['median']:.3f}",
                    f"{bigram['median']:.3f}",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _candidate_name(payload: dict[str, Any], path: Path) -> str:
    generation = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    model = generation.get("model")
    if model:
        return str(model)
    return path.stem


if __name__ == "__main__":
    raise SystemExit(main())
