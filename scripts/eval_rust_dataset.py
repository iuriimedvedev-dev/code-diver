#!/usr/bin/env python3
"""Run evaluation against code_diver_search_bin and output metrics matching compare_jbcontext.py."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from compare_jbcontext import (
    average_precision,
    dedupe_files,
    file_hit_at,
    file_metrics,
    mean,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin", default="native/code_diver_search_bin/target/release/code_diver_search_bin")
    parser.add_argument("--catalog", default="/tmp/rust_catalog.jsonl")
    parser.add_argument("--graph", default="/tmp/rust_graph.jsonl")
    parser.add_argument("--model", default="artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt")
    parser.add_argument("--embedding-url", default="http://127.0.0.1:8001/v1/embeddings")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--ce-url", default="http://127.0.0.1:18081/v1/rerank")
    parser.add_argument("--second-ce-url", default="http://127.0.0.1:18083/rerank")
    parser.add_argument("--preset", default="selective-strict")
    parser.add_argument("--candidate-limit", type=int, default=20)
    parser.add_argument("--dataset", default="datasets/intellij_eval_where_only.jsonl")
    parser.add_argument("--file-limit", type=int, default=10)
    parser.add_argument("--out", default=".code-diver/reports/rust-where78-fresh.json")
    args = parser.parse_args()

    cmd = [
        args.bin,
        "--catalog", args.catalog,
        "--graph", args.graph,
        "--model", args.model,
        "--embedding-url", args.embedding_url,
        "--qdrant-url", args.qdrant_url,
        "--ce-url", args.ce_url,
        "--second-ce-url", args.second_ce_url,
        "--preset", args.preset,
        "--candidate-limit", str(args.candidate_limit),
        "--server",
    ]

    print(f"Starting server: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # Wait for server ready message on stderr
    while True:
        line = proc.stderr.readline()
        if not line:
            print("Server exited unexpectedly during startup", file=sys.stderr)
            return 1
        print(line.rstrip(), file=sys.stderr)
        if "Server mode: reading queries" in line:
            break

    cases = [json.loads(line) for line in Path(args.dataset).read_text().splitlines() if line.strip()]
    results = []
    durations = []
    failed = 0

    for i, case in enumerate(cases, start=1):
        query = case["query"]
        expected = case["expected"]
        req = json.dumps({"query": query, "limit": args.file_limit * 2}) + "\n"
        
        t0 = time.perf_counter()
        proc.stdin.write(req)
        proc.stdin.flush()
        
        resp_line = proc.stdout.readline()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        durations.append(elapsed_ms)

        if not resp_line:
            stderr_rest = proc.stderr.read() if proc.stderr else ""
            print(f"Server closed pipe at query {i}: {query}\nServer STDERR:\n{stderr_rest}", file=sys.stderr)
            failed += 1
            results.append({
                "id": case.get("id", f"q-{i}"),
                "query": query,
                "expected": expected,
                "error": "server closed pipe",
                "duration_ms": elapsed_ms,
                "file_recall": 0.0,
                "file_hit": False,
                "file_mrr": 0.0,
                "ndcg": 0.0,
                "average_precision": 0.0,
                "retrieved_files": [],
            })
            continue

        try:
            resp = json.loads(resp_line)
            # results are list of items with "path"
            paths = [r["path"] for r in resp.get("results", [])]
            files = dedupe_files(paths)
            metrics = file_metrics(files, expected, args.file_limit)
            results.append({
                "id": case.get("id", f"q-{i}"),
                "query": query,
                "expected": expected,
                "duration_ms": elapsed_ms,
                "unique_file_count": len(files),
                **metrics,
            })
        except Exception as e:
            failed += 1
            results.append({
                "id": case.get("id", f"q-{i}"),
                "query": query,
                "expected": expected,
                "error": str(e),
                "duration_ms": elapsed_ms,
                "file_recall": 0.0,
                "file_hit": False,
                "file_mrr": 0.0,
                "ndcg": 0.0,
                "average_precision": 0.0,
                "retrieved_files": [],
            })

        if i % 5 == 0 or i == len(cases):
            print(f"[{i}/{len(cases)}] hit@10={mean([1.0 if r.get('file_hit') else 0.0 for r in results]):.3f} mean_ms={mean(durations):.1f}", file=sys.stderr, flush=True)

    proc.stdin.close()
    proc.terminate()

    summary = {
        "cases": len(results),
        "search_failed_cases": failed,
        "file_hit_rate@1": mean([1.0 if file_hit_at(r.get("retrieved_files", []), r["expected"], 1) else 0.0 for r in results]),
        "file_hit_rate@3": mean([1.0 if file_hit_at(r.get("retrieved_files", []), r["expected"], 3) else 0.0 for r in results]),
        "file_hit_rate@5": mean([1.0 if file_hit_at(r.get("retrieved_files", []), r["expected"], 5) else 0.0 for r in results]),
        f"file_hit_rate@{args.file_limit}": mean([1.0 if r["file_hit"] else 0.0 for r in results]),
        f"file_mrr@{args.file_limit}": mean([r["file_mrr"] for r in results]),
        f"file_recall@{args.file_limit}": mean([r["file_recall"] for r in results]),
        f"ndcg@{args.file_limit}": mean([r["ndcg"] for r in results]),
        f"map@{args.file_limit}": mean([r["average_precision"] for r in results]),
        "search_duration_ms_mean": mean(durations),
        "search_duration_ms_p95": sorted(durations)[int(len(durations) * 0.95) - 1] if durations else 0.0,
    }

    report = {
        "tool": "code_diver_rust",
        "dataset": args.dataset,
        "metrics": summary,
        "results": results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
