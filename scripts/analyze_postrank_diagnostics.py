from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


STAGES = [
    ("locator", "locator_rank"),
    ("candidates", "candidate_rank"),
    ("rerank", "rerank_rank"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze deterministic post-rank per-case diagnostics.")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    diagnostics = load_diagnostics(args.artifact)
    summary = summarize(diagnostics, args.limit)
    text = render(summary)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


def load_diagnostics(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload.get("diagnostics"), list):
        return [row for row in payload["diagnostics"] if isinstance(row, dict)]
    diagnostics: list[dict[str, Any]] = []
    for result in payload.get("results") or []:
        if isinstance(result, dict) and isinstance(result.get("diagnostics"), list):
            diagnostics.extend(row for row in result["diagnostics"] if isinstance(row, dict))
    return diagnostics


def summarize(diagnostics: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    total = len(diagnostics)
    stage_hits = {
        name: sum(1 for row in diagnostics if isinstance(row.get(rank_key), int))
        for name, rank_key in STAGES
    }
    source_counter: Counter[str] = Counter()
    for row in diagnostics:
        for source in row.get("expected_sources") or []:
            source_counter[str(source)] += 1
    miss_rows = [row for row in diagnostics if not isinstance(row.get("rerank_rank"), int)]
    lost_before_locator = [row for row in diagnostics if not isinstance(row.get("locator_rank"), int)]
    lost_after_locator = [
        row
        for row in diagnostics
        if isinstance(row.get("locator_rank"), int) and not isinstance(row.get("candidate_rank"), int)
    ]
    lost_after_candidates = [
        row
        for row in diagnostics
        if isinstance(row.get("candidate_rank"), int) and not isinstance(row.get("rerank_rank"), int)
    ]
    return {
        "cases": total,
        "stage_hits": stage_hits,
        "stage_rates": {name: safe_rate(count, total) for name, count in stage_hits.items()},
        "lost_before_locator": len(lost_before_locator),
        "lost_after_locator": len(lost_after_locator),
        "lost_after_candidates": len(lost_after_candidates),
        "source_hits": source_counter.most_common(),
        "miss_examples": miss_rows[:limit],
        "locator_miss_examples": lost_before_locator[:limit],
        "candidate_drop_examples": lost_after_locator[:limit],
        "rerank_drop_examples": lost_after_candidates[:limit],
    }


def safe_rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def render(summary: dict[str, Any]) -> str:
    lines = [
        "# Post-rank Diagnostics",
        "",
        f"Cases: {summary['cases']}",
        "",
        "## Stage Ceiling",
        "",
        "| Stage | Hits | Rate |",
        "| --- | ---: | ---: |",
    ]
    for name, _ in STAGES:
        lines.append(f"| {name} | {summary['stage_hits'][name]} | {summary['stage_rates'][name]:.3f} |")
    lines.extend(
        [
            "",
            "## Loss Breakdown",
            "",
            f"- Lost before locator: {summary['lost_before_locator']}",
            f"- Dropped after locator: {summary['lost_after_locator']}",
            f"- Dropped by rerank: {summary['lost_after_candidates']}",
            "",
            "## Expected Source Hits",
            "",
            "| Source | Hits |",
            "| --- | ---: |",
        ]
    )
    for source, count in summary["source_hits"]:
        lines.append(f"| {source} | {count} |")
    lines.extend(render_examples("Locator Miss Examples", summary["locator_miss_examples"]))
    lines.extend(render_examples("Candidate Drop Examples", summary["candidate_drop_examples"]))
    lines.extend(render_examples("Rerank Drop Examples", summary["rerank_drop_examples"]))
    return "\n".join(lines) + "\n"


def render_examples(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = ["", f"## {title}", ""]
    if not rows:
        lines.append("_None._")
        return lines
    lines.extend(["| Case | Query | Expected | Locator | Candidates | Rerank |", "| --- | --- | --- | ---: | ---: | ---: |"])
    for row in rows:
        expected = ", ".join(str(value) for value in row.get("expected") or [])
        lines.append(
            "| "
            + " | ".join(
                [
                    escape(str(row.get("case_id") or "")),
                    escape(str(row.get("query") or "")),
                    escape(expected),
                    rank(row.get("locator_rank")),
                    rank(row.get("candidate_rank")),
                    rank(row.get("rerank_rank")),
                ]
            )
            + " |"
        )
    return lines


def rank(value: Any) -> str:
    return str(value) if isinstance(value, int) else ""


def escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
