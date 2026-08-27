#!/usr/bin/env python3
"""Run the code-diver IntelliJ eval dataset through jbcontext search and score it
with the exact same file-level metric formulas as
src/code_diver/services/evaluation_service.py (_file_metrics/_ndcg/_average_precision),
so the two tools' numbers are directly comparable.

jbcontext returns overlapping *chunks*, not one row per file, so a --limit large enough
to surface >=10 unique files is requested per query, then deduped to unique files by
first-occurrence rank (same dedupe-then-slice semantics as code-diver's _dedupe_files).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import subprocess
import sys
import time
from pathlib import Path

JBCONTEXT_BIN = str(Path.home() / ".jbcontext" / "bin" / "jbcontext")


def matches_path_expected(path: str, expected: str) -> bool:
    normalized = expected.strip()
    if normalized.startswith("glob:"):
        return fnmatch.fnmatchcase(path, normalized.removeprefix("glob:"))
    return path == normalized or path.startswith(normalized.rstrip("/") + "/")


def matches_any_path_expected(path: str, expected: list[str]) -> bool:
    return any(matches_path_expected(path, value) for value in expected)


def first_unmatched_expected(path: str, expected: list[str], matched: set[int]) -> int | None:
    for index, value in enumerate(expected):
        if index in matched:
            continue
        if matches_path_expected(path, value):
            return index
    return None


def ndcg(files: list[str], expected: list[str], limit: int) -> float:
    dcg = 0.0
    matched: set[int] = set()
    for rank, path in enumerate(files[:limit], start=1):
        match_index = first_unmatched_expected(path, expected, matched)
        if match_index is not None:
            matched.add(match_index)
            dcg += 1.0 / math.log2(rank + 1)
    ideal_relevant = min(len(expected), limit)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    return dcg / ideal if ideal else 0.0


def average_precision(files: list[str], expected: list[str]) -> float:
    hits = 0
    total = 0.0
    matched: set[int] = set()
    for rank, path in enumerate(files, start=1):
        match_index = first_unmatched_expected(path, expected, matched)
        if match_index is None:
            continue
        matched.add(match_index)
        hits += 1
        total += hits / rank
    return total / max(len(expected), 1)


def dedupe_files(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def file_metrics(files: list[str], expected: list[str], limit: int) -> dict:
    top = files[:limit]
    matched_ranks = [rank for rank, path in enumerate(top, start=1) if matches_any_path_expected(path, expected)]
    expected_count = max(len(expected), 1)
    matched_expected_count = sum(1 for value in expected if any(matches_path_expected(path, value) for path in top))
    r = min(expected_count, limit)
    top_r = top[:r]
    file_precision_at_r = sum(1 for path in top_r if matches_any_path_expected(path, expected)) / max(r, 1)
    return {
        "retrieved_files": top,
        "file_hit": bool(matched_ranks),
        "file_mrr": 1.0 / matched_ranks[0] if matched_ranks else 0.0,
        "file_precision_at_r": file_precision_at_r,
        "file_recall": min(matched_expected_count / expected_count, 1.0),
        "ndcg": ndcg(top, expected, limit),
        "average_precision": average_precision(top, expected),
    }


def file_hit_at(files: list[str], expected: list[str], k: int) -> bool:
    return any(matches_any_path_expected(path, expected) for path in files[:k])


def run_jbcontext_search(
    project_path: str,
    query: str,
    raw_limit: int,
    timeout_s: float,
    revision: str | None,
    reranker: str | None,
) -> tuple[list[str], float, str | None]:
    started = time.perf_counter()
    cmd = [
        JBCONTEXT_BIN,
        "search",
        "--project-path",
        project_path,
        "--limit",
        str(raw_limit),
        "--json-output",
    ]
    if revision:
        cmd += ["--revision", revision]
    if reranker:
        cmd += ["--reranker", reranker]
    cmd.append(query)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        duration_ms = (time.perf_counter() - started) * 1000
        return [], duration_ms, "timeout"
    duration_ms = (time.perf_counter() - started) * 1000
    if proc.returncode != 0:
        return [], duration_ms, f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return [], duration_ms, f"bad json: {exc}"
    if payload.get("type") == "error":
        return [], duration_ms, payload.get("message", "unknown error")
    results = payload.get("results", [])
    paths = [r["result"]["sourcePosition"]["relativePath"] for r in results]
    return paths, duration_ms, None


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="datasets/intellij_eval_1000.answer_sets.jsonl")
    parser.add_argument("--project-path", default=str(Path.home() / "Work" / "intellij-community"))
    parser.add_argument("--limit-cases", type=int, default=0, help="0 = all cases")
    parser.add_argument("--raw-limit", type=int, default=40, help="raw chunk limit requested per query")
    parser.add_argument("--file-limit", type=int, default=10, help="unique-file cutoff to score against (matches @10)")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--out", default=".code-diver/reports/jbcontext-intellij-1000.json")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument(
        "--revision",
        default=None,
        help="pin jbcontext search to this exact indexed revision (must match an existing snapshot)",
    )
    parser.add_argument(
        "--reranker",
        default=None,
        choices=["OFF", "FAST", "BEST"],
        help="jbcontext reranker mode (undocumented CLI flag; default when omitted is jbcontext's own default, FAST)",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    cases = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
    if args.limit_cases:
        cases = cases[: args.limit_cases]

    results = []
    durations: list[float] = []
    failed = 0
    started_all = time.perf_counter()

    for i, case in enumerate(cases, start=1):
        query = case["query"]
        expected = case["expected"]
        paths, duration_ms, error = run_jbcontext_search(
            args.project_path, query, args.raw_limit, args.timeout_s, args.revision, args.reranker
        )
        durations.append(duration_ms)
        if error is not None:
            failed += 1
            results.append(
                {
                    "id": case.get("id", f"q-{i}"),
                    "query": query,
                    "expected": expected,
                    "error": error,
                    "duration_ms": duration_ms,
                    "file_recall": 0.0,
                    "file_hit": False,
                    "file_mrr": 0.0,
                    "ndcg": 0.0,
                    "average_precision": 0.0,
                    "retrieved_files": [],
                }
            )
        else:
            files = dedupe_files(paths)
            metrics = file_metrics(files, expected, args.file_limit)
            results.append(
                {
                    "id": case.get("id", f"q-{i}"),
                    "query": query,
                    "expected": expected,
                    "duration_ms": duration_ms,
                    "raw_chunk_count": len(paths),
                    "unique_file_count": len(files),
                    **metrics,
                }
            )
        if i % args.progress_every == 0 or i == len(cases):
            elapsed = time.perf_counter() - started_all
            print(
                f"[{i}/{len(cases)}] elapsed={elapsed:.0f}s failed={failed} "
                f"file_recall_running_mean={mean([r['file_recall'] for r in results]):.4f}",
                file=sys.stderr,
                flush=True,
            )

    n = max(len(results), 1)
    summary = {
        "cases": len(results),
        "search_failed_cases": failed,
        f"file_hit_rate@1": mean([1.0 if file_hit_at(r.get("retrieved_files", []), r["expected"], 1) else 0.0 for r in results]),
        f"file_hit_rate@3": mean([1.0 if file_hit_at(r.get("retrieved_files", []), r["expected"], 3) else 0.0 for r in results]),
        f"file_hit_rate@5": mean([1.0 if file_hit_at(r.get("retrieved_files", []), r["expected"], 5) else 0.0 for r in results]),
        f"file_hit_rate@{args.file_limit}": mean([1.0 if r["file_hit"] else 0.0 for r in results]),
        f"file_mrr@{args.file_limit}": mean([r["file_mrr"] for r in results]),
        f"file_recall@{args.file_limit}": mean([r["file_recall"] for r in results]),
        f"ndcg@{args.file_limit}": mean([r["ndcg"] for r in results]),
        f"map@{args.file_limit}": mean([r["average_precision"] for r in results]),
        "search_duration_ms_mean": mean(durations),
        "search_duration_ms_p95": sorted(durations)[int(len(durations) * 0.95) - 1] if durations else 0.0,
    }

    report = {
        "tool": "jbcontext",
        "dataset": str(dataset_path),
        "project_path": args.project_path,
        "revision": args.revision,
        "reranker": args.reranker,
        "raw_limit": args.raw_limit,
        "file_limit": args.file_limit,
        "metrics": summary,
        "results": results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nwrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
