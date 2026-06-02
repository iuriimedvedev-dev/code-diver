from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


RUNS = [
    {
        "id": "qwen35_4b",
        "ranker": "Qwen3.5 4B OptiQ 4bit",
        "final": ".code-diver/reports/intellij-postrank-h2-deterministic-qwen-1000.json",
        "partials": ".code-diver/reports/partials-qwen-1000",
    },
    {
        "id": "qwen35_4b_h3",
        "ranker": "Qwen3.5 4B OptiQ 4bit",
        "final": ".code-diver/reports/intellij-h3-union-qwen-1000.json",
        "partials": ".code-diver/reports/partials-h3-qwen-1000",
    },
    {
        "id": "qwen35_4b_h4",
        "ranker": "Qwen3.5 4B OptiQ 4bit",
        "final": ".code-diver/reports/intellij-h4-multiquery-qwen-1000.json",
        "partials": ".code-diver/reports/partials-h4-qwen-1000",
    },
    {
        "id": "gemini_flash_lite",
        "ranker": "Gemini 3.1 Flash-Lite",
        "final": ".code-diver/reports/intellij-postrank-h2-deterministic-gemini-flash-lite-1000.json",
        "partials": ".code-diver/reports/partials-gemini-flash-lite-1000",
    },
    {
        "id": "gemini_flash_lite_h3",
        "ranker": "Gemini 3.1 Flash-Lite",
        "final": ".code-diver/reports/intellij-h3-union-gemini-flash-lite-1000.json",
        "partials": ".code-diver/reports/partials-h3-gemini-flash-lite-1000",
    },
    {
        "id": "gemini_flash_lite_h4",
        "ranker": "Gemini 3.1 Flash-Lite",
        "final": ".code-diver/reports/intellij-h4-multiquery-gemini-flash-lite-1000.json",
        "partials": ".code-diver/reports/partials-h4-gemini-flash-lite-1000",
    },
    {
        "id": "gemini_flash_35",
        "ranker": "Gemini 3.5 Flash",
        "final": ".code-diver/reports/intellij-postrank-h2-deterministic-gemini-flash-35-1000.json",
        "partials": ".code-diver/reports/partials-gemini-flash-35-1000",
    },
    {
        "id": "gemini_flash_35_h3",
        "ranker": "Gemini 3.5 Flash",
        "final": ".code-diver/reports/intellij-h3-union-gemini-flash-35-1000.json",
        "partials": ".code-diver/reports/partials-h3-gemini-flash-35-1000",
    },
    {
        "id": "gemini_flash_35_h4",
        "ranker": "Gemini 3.5 Flash",
        "final": ".code-diver/reports/intellij-h4-multiquery-gemini-flash-35-1000.json",
        "partials": ".code-diver/reports/partials-h4-gemini-flash-35-1000",
    },
]

METRICS = [
    "hit_rate@1",
    "hit_rate@3",
    "hit_rate@5",
    "hit_rate@10",
    "precision@10",
    "recall@10",
    "file_recall@10",
    "mrr@10",
    "ndcg@10",
    "map@10",
    "search_duration_ms_mean",
    "search_duration_ms_p95",
    "degraded_cases",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize IntelliJ H2 post-rank matrix final and partial results.")
    parser.add_argument("--output", type=Path, default=Path("docs/intellij-h2-matrix-overnight-2026-06-02.md"))
    parser.add_argument("--json-output", type=Path, default=Path(".code-diver/reports/intellij-h2-matrix-overnight-summary.json"))
    args = parser.parse_args()

    rows = collect_rows()
    payload = {"rows": rows}
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(rows), encoding="utf-8")
    print(args.output)
    print(args.json_output)
    return 0


def collect_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in RUNS:
        final_path = Path(run["final"])
        if final_path.exists():
            rows.extend(rows_from_final(run, final_path))
            continue
        rows.extend(rows_from_partials(run, Path(run["partials"])))
    return sorted(rows, key=lambda row: (row["ranker"], row["scenario"]))


def rows_from_final(run: dict[str, str], path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics") or {}
        rows.append(normalize_row(run, item.get("hypothesis"), item.get("scenario"), "complete", metrics, item, path))
    return rows


def rows_from_partials(run: dict[str, str], partial_dir: Path) -> list[dict[str, Any]]:
    if not partial_dir.exists():
        return [
            normalize_row(
                run,
                hypothesis="missing",
                scenario="unknown",
                status="missing",
                metrics={},
                source={},
                path=partial_dir,
            )
        ]
    rows = []
    for path in sorted(partial_dir.glob("*.partial.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            normalize_row(
                run,
                payload.get("hypothesis"),
                payload.get("scenario"),
                "partial",
                payload.get("metrics") or {},
                payload,
                path,
            )
        )
    return rows


def normalize_row(
    run: dict[str, str],
    hypothesis: Any,
    scenario: Any,
    status: str,
    metrics: dict[str, Any],
    source: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    cases = int(
        source.get("completed_cases")
        or metrics.get("cases")
        or source.get("benchmark", {}).get("cases")
        or 0
    )
    normalized = {
        "run_id": run["id"],
        "ranker": run["ranker"],
        "hypothesis": str(hypothesis or ""),
        "scenario": str(scenario or ""),
        "status": status,
        "cases": cases,
        "artifact": str(path),
        "metrics": metrics,
        "orchestrator_usage": source.get("orchestrator_usage") or {},
        "tool_metrics": source.get("tool_metrics") or {},
    }
    hit1 = metrics.get("hit_rate@1")
    if isinstance(hit1, int | float) and cases:
        low, high = wilson(float(hit1), cases)
        normalized["hit1_ci95_low"] = low
        normalized["hit1_ci95_high"] = high
        normalized["hit1_ci95_width"] = high - low
    return normalized


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# IntelliJ H2 Overnight Matrix",
        "",
        "Generated by `scripts/summarize_h2_matrix.py`.",
        "",
        "The matrix compares two post-locator scenarios over the same local Qwen file-locator index:",
        "",
        "- Branch A: locator -> outline/symbol/rg probes -> listwise ranker.",
        "- Branch B: locator -> ephemeral syntax-aware vector index over candidate files -> listwise ranker.",
        "- Branch C: union of multiple locator profiles -> outline/symbol/rg probes -> listwise ranker.",
        "- Branch D: LLM query planner -> multi-query locator profiles -> outline/symbol/rg probes -> listwise ranker.",
        "",
        "Gemini rows use Vertex model IDs when the artifacts exist. Local rows use the MLX OpenAI-compatible server.",
        "",
        "## Summary",
        "",
        "| Ranker | Scenario | Status | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Degraded | Hit@1 95% CI | Artifact |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        metrics = row["metrics"]
        ci = ""
        if "hit1_ci95_low" in row:
            ci = f"{row['hit1_ci95_low']:.3f}..{row['hit1_ci95_high']:.3f}"
        lines.append(
            "| "
            + " | ".join(
                [
                    row["ranker"],
                    row["scenario"],
                    row["status"],
                    str(row["cases"]),
                    fmt(metrics.get("hit_rate@1")),
                    fmt(metrics.get("hit_rate@3")),
                    fmt(metrics.get("hit_rate@5")),
                    fmt(metrics.get("hit_rate@10")),
                    fmt(metrics.get("precision@10")),
                    fmt(metrics.get("recall@10")),
                    fmt(metrics.get("mrr@10")),
                    fmt(metrics.get("ndcg@10")),
                    fmt(metrics.get("search_duration_ms_mean"), digits=0),
                    fmt(metrics.get("search_duration_ms_p95"), digits=0),
                    str(metrics.get("degraded_cases", "")),
                    ci,
                    f"`{row['artifact']}`",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Tool And Cost Signals",
            "",
            "| Ranker | Scenario | Model Calls | Input Tokens | Output Tokens | Total Tokens | Estimated Cost | Tool Metrics |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        usage = row.get("orchestrator_usage") or {}
        tool_metrics = row.get("tool_metrics") or {}
        compact_tool_metrics = {
            key: tool_metrics.get(key)
            for key in [
                "locator_calls",
                "outline_calls",
                "symbol_calls",
                "rg_calls",
                "ephemeral_calls",
                "union_profile_calls",
                "union_candidate_count_total",
                "planner_calls",
                "planner_errors",
                "query_variant_total",
                "rerank_calls",
                "rerank_errors",
                "candidate_count_mean",
                "temporary_vectors_total",
            ]
            if key in tool_metrics
        }
        lines.append(
            "| "
            + " | ".join(
                [
                    row["ranker"],
                    row["scenario"],
                    str(usage.get("model_calls", "")),
                    str(usage.get("input_tokens", "")),
                    str(usage.get("output_tokens", "")),
                    str(usage.get("total_tokens", "")),
                    fmt(usage.get("total_cost"), digits=4),
                    f"`{json.dumps(compact_tool_metrics, sort_keys=True)}`",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Notes",
            "",
            "- `Hit@1` is the strict user-facing metric: the first returned file is correct or it is not.",
            "- `Hit@3/5/10` show whether the correct file is in the small candidate set a human or follow-up tool could inspect.",
            "- `Precision@10` is low by construction on the current IntelliJ dataset because most cases have one gold file.",
            "- `Recall@10` and `File Recall@10` are more useful for the current single-answer dataset.",
            "- The Wilson interval on `Hit@1` shows how unstable partial runs are. A wide interval means do not trust small differences.",
        ]
    )
    return "\n".join(lines) + "\n"


def fmt(value: Any, digits: int = 3) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, int | float):
        return f"{float(value):.{digits}f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
