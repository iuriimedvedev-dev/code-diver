#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from statistics import mean
from typing import Any


PRIMARY_METRICS = [
    "hit_rate@1",
    "hit_rate@3",
    "hit_rate@5",
    "hit_rate@10",
    "mrr@10",
    "ndcg@10",
    "map@10",
    "file_recall@10",
    "search_duration_ms_mean",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a static HTML comparison report from code-diver eval JSON.")
    parser.add_argument(
        "input",
        type=Path,
        help="JSON file from `evaluate --json`, `experiment --json`, or direct evaluation commands.",
    )
    parser.add_argument("--output", type=Path, required=True, help="HTML report path.")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows = normalize_rows(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(rows, payload), encoding="utf-8")
    print(args.output)
    return 0


def normalize_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("metrics"), dict):
        return [
            {
                "name": str(payload.get("strategy") or payload.get("hypothesis") or "evaluate"),
                "metrics": payload["metrics"],
                "results": payload.get("results") or [],
                "tools": payload.get("tools") or [],
                "error_count": payload.get("error_count", 0),
            }
        ]
    raw_rows = payload.get("results") or payload.get("strategies") or payload.get("strategy_results") or []
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") or {}
        if not isinstance(metrics, dict):
            continue
        rows.append(
            {
                "name": str(row.get("hypothesis") or row.get("strategy") or f"strategy_{index + 1}"),
                "metrics": metrics,
                "results": row.get("results") or [],
                "tools": row.get("tools") or [],
                "error_count": row.get("error_count", 0),
            }
        )
    return rows


def render_report(rows: list[dict[str, Any]], payload: dict[str, Any]) -> str:
    metric_names = [name for name in PRIMARY_METRICS if any(name in row["metrics"] for row in rows)]
    return "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset='utf-8'>",
            "<title>Code Diver Eval Report</title>",
            styles(),
            "</head><body>",
            f"<h1>Code Diver Eval Report</h1><p>run_id: <code>{escape(payload.get('run_id', 'unknown'))}</code></p>",
            summary_table(rows, metric_names),
            *(metric_chart(rows, metric) for metric in metric_names),
            *(distribution_section(row) for row in rows),
            "</body></html>",
        ]
    )


def summary_table(rows: list[dict[str, Any]], metric_names: list[str]) -> str:
    headers = "".join(f"<th>{escape(metric)}</th>" for metric in metric_names)
    body = []
    for row in rows:
        cells = [f"<td><strong>{escape(row['name'])}</strong></td>"]
        for metric in metric_names:
            value = row["metrics"].get(metric)
            ci_low = row["metrics"].get(f"{metric}_ci95_low")
            ci_high = row["metrics"].get(f"{metric}_ci95_high")
            cells.append(f"<td>{format_metric(value, ci_low, ci_high)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<h2>Summary With 95% CI</h2><table><thead><tr><th>hypothesis</th>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def metric_chart(rows: list[dict[str, Any]], metric: str) -> str:
    width = 920
    height = max(160, 44 * len(rows) + 60)
    left = 260
    right = 40
    max_value = max([float(row["metrics"].get(metric) or 0.0) for row in rows] + [1.0])
    bars = []
    for index, row in enumerate(rows):
        value = float(row["metrics"].get(metric) or 0.0)
        low = row["metrics"].get(f"{metric}_ci95_low")
        high = row["metrics"].get(f"{metric}_ci95_high")
        y = 34 + index * 44
        bar_width = int((width - left - right) * value / max_value)
        bars.append(f"<text x='8' y='{y + 16}'>{escape(row['name'])}</text>")
        bars.append(f"<rect x='{left}' y='{y}' width='{bar_width}' height='24' rx='3'></rect>")
        bars.append(f"<text x='{left + bar_width + 8}' y='{y + 17}'>{value:.3f}</text>")
        if isinstance(low, int | float) and isinstance(high, int | float):
            x1 = left + int((width - left - right) * float(low) / max_value)
            x2 = left + int((width - left - right) * float(high) / max_value)
            bars.append(f"<line class='ci' x1='{x1}' y1='{y + 12}' x2='{x2}' y2='{y + 12}'></line>")
            bars.append(f"<line class='ci' x1='{x1}' y1='{y + 6}' x2='{x1}' y2='{y + 18}'></line>")
            bars.append(f"<line class='ci' x1='{x2}' y1='{y + 6}' x2='{x2}' y2='{y + 18}'></line>")
    return f"<h2>{escape(metric)}</h2><svg viewBox='0 0 {width} {height}'>{''.join(bars)}</svg>"


def distribution_section(row: dict[str, Any]) -> str:
    results = [item for item in row.get("results") or [] if isinstance(item, dict)]
    if not results:
        return ""
    hit_values = [1.0 if item.get("hit") else 0.0 for item in results]
    rr_values = [float(item.get("reciprocal_rank") or 0.0) for item in results]
    recall_values = [float(item.get("recall") or 0.0) for item in results]
    return "\n".join(
        [
            f"<h2>Per-case distributions: {escape(row['name'])}</h2>",
            histogram("hit", hit_values, buckets=2),
            histogram("reciprocal_rank", rr_values, buckets=10),
            histogram("recall", recall_values, buckets=10),
        ]
    )


def histogram(name: str, values: list[float], buckets: int) -> str:
    if not values:
        return ""
    counts = [0] * buckets
    for value in values:
        index = min(int(max(value, 0.0) * buckets), buckets - 1)
        counts[index] += 1
    width = 920
    height = 170
    max_count = max(counts) or 1
    bar_width = width // buckets
    bars = []
    for index, count in enumerate(counts):
        bar_height = int((height - 50) * count / max_count)
        x = index * bar_width + 4
        y = height - bar_height - 28
        bars.append(f"<rect x='{x}' y='{y}' width='{bar_width - 8}' height='{bar_height}' rx='3'></rect>")
        bars.append(f"<text x='{x}' y='{height - 8}'>{index / buckets:.1f}</text>")
        bars.append(f"<text x='{x}' y='{y - 5}'>{count}</text>")
    return f"<h3>{escape(name)} mean={mean(values):.3f}</h3><svg viewBox='0 0 {width} {height}'>{''.join(bars)}</svg>"


def format_metric(value: Any, ci_low: Any, ci_high: Any) -> str:
    if not isinstance(value, int | float):
        return ""
    text = f"{float(value):.4f}"
    if isinstance(ci_low, int | float) and isinstance(ci_high, int | float):
        text += f"<br><small>[{float(ci_low):.4f}, {float(ci_high):.4f}]</small>"
    return text


def escape(value: Any) -> str:
    return html.escape(str(value))


def styles() -> str:
    return """
<style>
body { font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; color: #172026; background: #f7f8fa; }
h1, h2, h3 { letter-spacing: 0; }
table { border-collapse: collapse; width: 100%; margin: 16px 0 28px; background: white; }
th, td { border: 1px solid #d8dee8; padding: 8px 10px; text-align: right; vertical-align: top; }
th:first-child, td:first-child { text-align: left; }
th { background: #edf2f7; }
small { color: #52606d; }
svg { width: 100%; background: white; border: 1px solid #d8dee8; margin-bottom: 18px; }
rect { fill: #276ef1; }
line.ci { stroke: #111827; stroke-width: 2; }
text { font-size: 13px; fill: #172026; }
code { background: #e9eef5; padding: 2px 5px; border-radius: 4px; }
</style>
"""


if __name__ == "__main__":
    raise SystemExit(main())
