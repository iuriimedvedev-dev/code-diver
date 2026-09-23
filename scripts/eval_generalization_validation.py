#!/usr/bin/env python3
"""Validate latency and quality generalizations outside WHERE-only on intellij_eval_1000.answer_sets.jsonl (100 query slice)."""

import argparse
import fnmatch
import json
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path
import numpy as np

DATASET_PATH = Path("datasets/intellij_eval_1000.answer_sets.jsonl")
BIN_PATH = Path("native/code_diver_search_bin/target/release/code_diver_search_bin")
CATALOG_PATH = Path("/tmp/rust_catalog.jsonl")
GRAPH_PATH = Path("/tmp/rust_graph.jsonl")
MODEL_PATH = Path("artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt")
CE_URL = "http://127.0.0.1:18083/rerank"
CE_MODEL = "mlx-community/Qwen3-Reranker-0.6B-4bit"


def matches_path_expected(path: str, expected: str) -> bool:
    normalized = expected.strip()
    if normalized.startswith("glob:"):
        return fnmatch.fnmatchcase(path, normalized.removeprefix("glob:"))
    return path == normalized or path.startswith(normalized.rstrip("/") + "/")


def matches_any_path_expected(path: str, expected: list[str]) -> bool:
    return any(matches_path_expected(path, value) for value in expected)


class NativeSearchServer:
    def __init__(self, extra_args):
        self.cmd = [
            str(BIN_PATH),
            "--server",
            "--catalog", str(CATALOG_PATH),
            "--graph", str(GRAPH_PATH),
            "-m", str(MODEL_PATH),
            "--ce-url", CE_URL,
            "--ce-model", CE_MODEL,
            "--limit", "10",
        ] + extra_args

        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._wait_ready()

    def _wait_ready(self):
        while True:
            line = self.proc.stderr.readline()
            if not line:
                break
            if "Server mode: reading queries" in line:
                break

        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        # Warmup queries
        self.query("where is project open")
        self.query("java manifest util")

    def _drain_stderr(self):
        try:
            for line in iter(self.proc.stderr.readline, ""):
                if "ERROR" in line or "WARN" in line:
                    print(f"[{self.proc.pid} stderr] {line.strip()}", file=sys.stderr)
        except Exception:
            pass

    def query(self, text: str):
        req = json.dumps({"query": text, "limit": 10}) + "\n"
        self.proc.stdin.write(req)
        self.proc.stdin.flush()
        ready = select.select([self.proc.stdout], [], [], 60)[0]
        if not ready:
            raise TimeoutError(f"Query timed out: {text}")
        line = self.proc.stdout.readline()
        return json.loads(line)

    def close(self):
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        try:
            if self.proc.stdout and not self.proc.stdout.closed:
                self.proc.stdout.close()
            if self.proc.stderr and not self.proc.stderr.closed:
                self.proc.stderr.close()
        except Exception:
            pass
        if hasattr(self, "_stderr_thread") and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1)


def evaluate_config(cfg_name, extra_args, cases):
    print(f"\n=======================================================", flush=True)
    print(f"Running Configuration: {cfg_name}", flush=True)
    print(f"Args: {' '.join(extra_args)}", flush=True)
    print(f"=======================================================", flush=True)
    server = NativeSearchServer(extra_args)

    hits1 = 0
    hits3 = 0
    hits10 = 0
    reciprocal_ranks = []
    total_ms_list = []
    ce_ms_list = []
    ce_p1_ms_list = []
    ce_p2_ms_list = []
    bm25_ms_list = []
    vector_ms_list = []

    bucket_stats = {}

    for idx, case in enumerate(cases):
        q = case["query"]
        expected = case.get("expected", [])
        if not expected and "expected_path" in case:
            expected = [case["expected_path"]]

        bucket = case["id"].split("-")[0]
        if bucket not in bucket_stats:
            bucket_stats[bucket] = {"hits1": 0, "hits3": 0, "hits10": 0, "rrs": [], "count": 0}

        t0 = time.perf_counter()
        res = server.query(q)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        results = res.get("results", [])
        retrieved_paths = [r["path"] for r in results]

        hit1 = any(matches_any_path_expected(p, expected) for p in retrieved_paths[:1])
        hit3 = any(matches_any_path_expected(p, expected) for p in retrieved_paths[:3])
        hit10 = any(matches_any_path_expected(p, expected) for p in retrieved_paths[:10])

        hits1 += int(hit1)
        hits3 += int(hit3)
        hits10 += int(hit10)

        rr = 0.0
        for rank, p in enumerate(retrieved_paths[:10], start=1):
            if matches_any_path_expected(p, expected):
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

        bucket_stats[bucket]["count"] += 1
        bucket_stats[bucket]["hits1"] += int(hit1)
        bucket_stats[bucket]["hits3"] += int(hit3)
        bucket_stats[bucket]["hits10"] += int(hit10)
        bucket_stats[bucket]["rrs"].append(rr)

        timings = res.get("timings", {})
        total_ms = timings.get("total_ms", elapsed_ms)
        p1 = timings.get("ce_first_pass_ms", 0.0)
        p2 = timings.get("ce_second_pass_ms", 0.0)
        ce_ms = p1 + p2
        bm25_ms = timings.get("bm25_ms", 0.0)
        vec_ms = timings.get("vector_search_ms", 0.0)

        total_ms_list.append(total_ms)
        ce_ms_list.append(ce_ms)
        ce_p1_ms_list.append(p1)
        ce_p2_ms_list.append(p2)
        bm25_ms_list.append(bm25_ms)
        vector_ms_list.append(vec_ms)

        if (idx + 1) % 20 == 0 or idx + 1 == len(cases):
            print(f"[{idx+1}/{len(cases)}] curr MRR: {np.mean(reciprocal_ranks):.3f}, avg total: {np.mean(total_ms_list):.1f}ms (CE p1: {np.mean(ce_p1_ms_list):.1f}ms, p2: {np.mean(ce_p2_ms_list):.1f}ms)", flush=True)

    server.close()

    n = len(cases)
    per_bucket = {}
    for b, s in bucket_stats.items():
        per_bucket[b] = {
            "count": s["count"],
            "hit@1": s["hits1"] / s["count"],
            "hit@3": s["hits3"] / s["count"],
            "hit@10": s["hits10"] / s["count"],
            "mrr@10": float(np.mean(s["rrs"])),
        }

    report = {
        "name": cfg_name,
        "args": extra_args,
        "num_cases": n,
        "hit@1": hits1 / n,
        "hit@3": hits3 / n,
        "hit@10": hits10 / n,
        "mrr@10": float(np.mean(reciprocal_ranks)),
        "latency_mean_ms": float(np.mean(total_ms_list)),
        "latency_p50_ms": float(np.percentile(total_ms_list, 50)),
        "latency_p95_ms": float(np.percentile(total_ms_list, 95)),
        "ce_mean_ms": float(np.mean(ce_ms_list)),
        "ce_p1_mean_ms": float(np.mean(ce_p1_ms_list)),
        "ce_p2_mean_ms": float(np.mean(ce_p2_ms_list)),
        "ce_p50_ms": float(np.percentile(ce_ms_list, 50)),
        "ce_p95_ms": float(np.percentile(ce_ms_list, 95)),
        "bm25_mean_ms": float(np.mean(bm25_ms_list)),
        "vector_mean_ms": float(np.mean(vector_ms_list)),
        "per_bucket": per_bucket,
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-cases", type=int, default=100)
    parser.add_argument("--config-index", type=int, default=None, help="Run only specific config index (0-based)")
    parser.add_argument("--out", default="artifacts/research/generalization_benchmark_100.json")
    args = parser.parse_args()

    cases = []
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            cases.append(json.loads(line))
            if len(cases) >= args.num_cases:
                break

    print(f"Loaded {len(cases)} cases from {DATASET_PATH}")
    from collections import Counter
    print("Bucket distribution:", Counter(c["id"].split("-")[0] for c in cases))

    configs = [
        {
            "name": "1. Baseline (default: cap 34, 2nd cap 24, doc 850/2400)",
            "args": [
                "--candidate-limit", "34",
                "--second-pass-cap", "24",
                "--second-pass-floor", "0.3",
                "--retrieval-limit", "360",
                "--max-document-chars", "850",
                "--second-pass-max-document-chars", "2400",
            ],
        },
        {
            "name": "2. Optimized Profile (--preset selective-strict, doc 450/1200)",
            "args": [
                "--candidate-limit", "34",
                "--preset", "selective-strict",
                "--retrieval-limit", "360",
                "--max-document-chars", "450",
                "--second-pass-max-document-chars", "1200",
            ],
        },
        {
            "name": "3. Optimized Profile (first-pass 24, selective-strict, doc 450/1200)",
            "args": [
                "--candidate-limit", "24",
                "--preset", "selective-strict",
                "--retrieval-limit", "360",
                "--max-document-chars", "450",
                "--second-pass-max-document-chars", "1200",
            ],
        },
        {
            "name": "4. Optimized Profile (first-pass 24, second-pass 16, doc 450/1200)",
            "args": [
                "--candidate-limit", "24",
                "--second-pass-cap", "16",
                "--second-pass-floor", "0.3",
                "--retrieval-limit", "360",
                "--max-document-chars", "450",
                "--second-pass-max-document-chars", "1200",
            ],
        },
    ]

    out_file = Path(args.out)
    existing_reports = {}
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for r in loaded:
                    existing_reports[r["name"]] = r
        except Exception:
            pass

    selected_configs = configs
    if args.config_index is not None:
        selected_configs = [configs[args.config_index]]

    for cfg in selected_configs:
        rep = evaluate_config(cfg["name"], cfg["args"], cases)
        existing_reports[cfg["name"]] = rep

    all_reports = [existing_reports[c["name"]] for c in configs if c["name"] in existing_reports]

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, indent=2)

    print("\n\n" + "=" * 120, flush=True)
    print(f"{'Configuration':<50} | {'H@1':<6} | {'H@3':<6} | {'H@10':<6} | {'MRR':<6} | {'Mean Total':<11} | {'CE Mean':<10} | {'p95 Total':<10}", flush=True)
    print("-" * 120, flush=True)
    for r in all_reports:
        print(f"{r['name']:<50} | {r['hit@1']*100:5.1f}% | {r['hit@3']*100:5.1f}% | {r['hit@10']*100:5.1f}% | {r['mrr@10']:5.3f} | {r['latency_mean_ms']:8.1f} ms | {r['ce_mean_ms']:7.1f} ms | {r['latency_p95_ms']:7.1f} ms", flush=True)
    print("=" * 120, flush=True)

    print("\nPer-Bucket Breakdown:")
    for r in all_reports:
        print(f"\n--- {r['name']} ---")
        for b, s in r["per_bucket"].items():
            print(f"  {b:<8} (n={s['count']:2d}): Hit@1={s['hit@1']*100:5.1f}%, Hit@3={s['hit@3']*100:5.1f}%, Hit@10={s['hit@10']*100:5.1f}%, MRR={s['mrr@10']:5.3f}")


if __name__ == "__main__":
    main()
