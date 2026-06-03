from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize eval result JSON files into a comparison matrix.")
    parser.add_argument("--input-glob", action="append", required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--title", default="Evaluation Matrix")
    args = parser.parse_args()

    rows = load_rows(args.input_glob)
    rows.sort(key=lambda row: (row["hit_rate@10"], row["hit_rate@5"], row["mrr@10"]), reverse=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(args.title, rows), encoding="utf-8")
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print(args.output_md)
    if args.output_json is not None:
        print(args.output_json)
    return 0


def load_rows(patterns: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern in patterns:
        for path in sorted(Path().glob(pattern)):
            document = json.loads(path.read_text(encoding="utf-8"))
            benchmark = document.get("benchmark") or {}
            for result in document.get("results", []):
                metrics = result.get("metrics") or {}
                usage = result.get("orchestrator_usage") or {}
                rows.append(
                    {
                        "hypothesis": result.get("hypothesis"),
                        "scenario": result.get("scenario"),
                        "cases": metrics.get("cases"),
                        "hit_rate@1": as_float(metrics.get("hit_rate@1")),
                        "hit_rate@3": as_float(metrics.get("hit_rate@3")),
                        "hit_rate@5": as_float(metrics.get("hit_rate@5")),
                        "hit_rate@10": as_float(metrics.get("hit_rate@10")),
                        "recall@10": as_float(metrics.get("recall@10")),
                        "precision@10": as_float(metrics.get("precision@10")),
                        "mrr@10": as_float(metrics.get("mrr@10")),
                        "ndcg@10": as_float(metrics.get("ndcg@10")),
                        "mean_ms": as_float(metrics.get("search_duration_ms_mean")),
                        "p95_ms": as_float(metrics.get("search_duration_ms_p95")),
                        "cost": as_float(usage.get("total_cost")),
                        "total_tokens": int(usage.get("total_tokens") or 0),
                        "model_calls": int(usage.get("model_calls") or 0),
                        "degraded_cases": int(metrics.get("degraded_cases") or 0),
                        "artifact": str(path),
                        "config": benchmark.get("config"),
                        "dataset": benchmark.get("dataset"),
                    }
                )
    return rows


def render_markdown(title: str, rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# {title}",
        "",
        "| Hypothesis | Branch | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | NDCG@10 | Mean ms | P95 ms | Cost | Tokens | Degraded | Artifact |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["hypothesis"]),
                    branch_label(str(row["scenario"])),
                    str(row["cases"]),
                    format_float(row["hit_rate@1"]),
                    format_float(row["hit_rate@3"]),
                    format_float(row["hit_rate@5"]),
                    format_float(row["hit_rate@10"]),
                    format_float(row["recall@10"]),
                    format_float(row["precision@10"]),
                    format_float(row["mrr@10"]),
                    format_float(row["ndcg@10"]),
                    format_float(row["mean_ms"], digits=0),
                    format_float(row["p95_ms"], digits=0),
                    format_float(row["cost"], digits=2),
                    str(row["total_tokens"]),
                    str(row["degraded_cases"]),
                    f"`{row['artifact']}`",
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def branch_label(scenario: str) -> str:
    return {
        "branch_a": "A grep/read",
        "branch_b": "B ephemeral vectors",
        "branch_c": "C union locator",
        "branch_d": "D multi-query",
    }.get(scenario, scenario)


def as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_float(value: Any, *, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
