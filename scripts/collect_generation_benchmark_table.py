from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = []
    for report in args.reports:
        rows.extend(_rows(report))
    rows.sort(key=lambda row: (row["model_name"], row["strategy"], row["source"]))
    text = _markdown(rows)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def _rows(report: Path) -> list[dict[str, Any]]:
    data = json.loads(report.read_text(encoding="utf-8"))
    rows = []
    for result in data.get("results", []):
        for evaluation in result.get("evaluations", []):
            metrics = evaluation.get("metrics", {})
            usage = metrics.get("llm_usage", {})
            rows.append(
                {
                    "source": report.name,
                    "model_name": result.get("name", ""),
                    "model": result.get("model", ""),
                    "precision": result.get("precision", ""),
                    "quantization": result.get("quantization", ""),
                    "strategy": evaluation.get("strategy", ""),
                    "startup_s": _rounded((result.get("server", {}).get("startup_duration_ms") or 0) / 1000, 1),
                    "hit1": _rounded(metrics.get("hit_rate@1"), 3),
                    "hit10": _rounded(metrics.get("hit_rate@10"), 3),
                    "mrr": _rounded(metrics.get("mrr@10"), 3),
                    "ndcg": _rounded(metrics.get("ndcg@10"), 3),
                    "map": _rounded(metrics.get("map@10"), 3),
                    "mean_ms": _rounded(metrics.get("search_duration_ms_mean"), 1),
                    "p95_ms": _rounded(metrics.get("search_duration_ms_p95"), 1),
                    "calls": usage.get("calls", 0),
                    "errors": usage.get("errors", 0),
                    "tokens": usage.get("total_tokens", 0),
                }
            )
    return rows


def _rounded(value: Any, digits: int) -> Any:
    if value is None:
        return ""
    return round(float(value), digits)


def _markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| source | model | strategy | precision | quant | startup_s | hit@1 | hit@10 | mrr | ndcg | map | mean_ms | p95_ms | calls | errors | tokens |",
        "|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {source} | `{model_name}` | `{strategy}` | {precision} | {quantization} | {startup_s} | "
            "{hit1} | {hit10} | {mrr} | {ndcg} | {map} | {mean_ms} | {p95_ms} | {calls} | {errors} | {tokens} |".format(
                **row
            )
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
