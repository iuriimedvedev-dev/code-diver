#!/usr/bin/env python3
"""Run candidate limit hypotheses benchmark on WHERE-only test set (78 queries).

Hypotheses:
- H1: Baseline candidate-limit 34 (MLX 18083)
- H2: candidate-limit 24 (MLX 18083)
- H3: candidate-limit 16 (MLX 18083)
- H4: candidate-limit 12 (MLX 18083)
- H5: candidate-limit 8  (MLX 18083)

Measures:
- Hit@1, Hit@3, Hit@10
- MRR@10
- Timings: total_ms, ce_ms, bm25_ms, vector_search_ms (mean, p50, p95)
"""

import json
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path
import numpy as np

DATASET_PATH = Path("datasets/intellij_eval_where_only.jsonl")
BIN_PATH = Path("native/code_diver_search_bin/target/release/code_diver_search_bin")
CATALOG_PATH = Path("/tmp/rust_catalog.jsonl")
GRAPH_PATH = Path("/tmp/rust_graph.jsonl")
MODEL_PATH = Path("artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt")
CE_URL = "http://127.0.0.1:18083/rerank"
CE_MODEL = "mlx-community/Qwen3-Reranker-0.6B-4bit"

HYPOTHESES = [
    {"name": "H1_cap34", "first_cap": 34, "second_cap": 24},
    {"name": "H2_cap24", "first_cap": 24, "second_cap": 16},
    {"name": "H3_cap16", "first_cap": 16, "second_cap": 10},
    {"name": "H4_cap12", "first_cap": 12, "second_cap": 8},
    {"name": "H5_cap8",  "first_cap": 8,  "second_cap": 4},
]


def load_dataset():
    cases = []
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            cases.append(json.loads(line))
    return cases


class NativeSearchServer:
    def __init__(self, first_cap: int, second_cap: int):
        self.cmd = [
            str(BIN_PATH),
            "--server",
            "--catalog", str(CATALOG_PATH),
            "--graph", str(GRAPH_PATH),
            "-m", str(MODEL_PATH),
            "--ce-url", CE_URL,
            "--ce-model", CE_MODEL,
            "--first-pass-cap", str(first_cap),
            "--second-pass-cap", str(second_cap),
            "--limit", "10",
        ]
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
        # Read stderr until ready
        while True:
            line = self.proc.stderr.readline()
            if not line:
                break
            if "Server mode: reading queries" in line:
                break

        # Drain stderr in a background thread to prevent OS pipe buffers from filling and deadlocking
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

        # Consume the warm query stdout so it does not block the buffer
        self.query("where is project open")

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


def evaluate_hypothesis(hypo, cases):
    print(f"\n==========================================", flush=True)
    print(f"Starting {hypo['name']} (first_pass={hypo['first_cap']}, second_pass={hypo['second_cap']})", flush=True)
    print(f"==========================================", flush=True)
    server = NativeSearchServer(hypo["first_cap"], hypo["second_cap"])

    hits1 = 0
    hits3 = 0
    hits10 = 0
    reciprocal_ranks = []
    total_ms_list = []
    ce_ms_list = []
    bm25_ms_list = []
    vector_ms_list = []

    # Warm-up 1 query
    # server.query("where is project open")

    for idx, case in enumerate(cases):
        q = case["query"]
        expected = set(case.get("expected", []))
        if not expected and "expected_path" in case:
            expected = {case["expected_path"]}

        t0 = time.perf_counter()
        res = server.query(q)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        results = res.get("results", [])
        retrieved_paths = [r["path"] for r in results]

        # Check hits
        hit1 = any(p in expected for p in retrieved_paths[:1])
        hit3 = any(p in expected for p in retrieved_paths[:3])
        hit10 = any(p in expected for p in retrieved_paths[:10])

        hits1 += int(hit1)
        hits3 += int(hit3)
        hits10 += int(hit10)

        # MRR
        rr = 0.0
        for rank, p in enumerate(retrieved_paths[:10], start=1):
            if p in expected:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

        timings = res.get("timings", {})
        total_ms = timings.get("total_ms", elapsed_ms)
        ce_ms = timings.get("ce_first_pass_ms", 0.0) + timings.get("ce_second_pass_ms", 0.0)
        bm25_ms = timings.get("bm25_ms", 0.0)
        vec_ms = timings.get("vector_search_ms", 0.0)

        total_ms_list.append(total_ms)
        ce_ms_list.append(ce_ms)
        bm25_ms_list.append(bm25_ms)
        vector_ms_list.append(vec_ms)

        if (idx + 1) % 20 == 0 or idx + 1 == len(cases):
            print(f"[{idx+1}/{len(cases)}] curr MRR: {np.mean(reciprocal_ranks):.3f}, curr avg latency: {np.mean(total_ms_list):.1f}ms", flush=True)

    server.close()

    n = len(cases)
    report = {
        "hypothesis": hypo["name"],
        "first_cap": hypo["first_cap"],
        "second_cap": hypo["second_cap"],
        "num_cases": n,
        "hit@1": hits1 / n,
        "hit@3": hits3 / n,
        "hit@10": hits10 / n,
        "mrr@10": float(np.mean(reciprocal_ranks)),
        "latency_mean_ms": float(np.mean(total_ms_list)),
        "latency_p50_ms": float(np.percentile(total_ms_list, 50)),
        "latency_p95_ms": float(np.percentile(total_ms_list, 95)),
        "ce_mean_ms": float(np.mean(ce_ms_list)),
        "ce_p50_ms": float(np.percentile(ce_ms_list, 50)),
        "ce_p95_ms": float(np.percentile(ce_ms_list, 95)),
        "bm25_mean_ms": float(np.mean(bm25_ms_list)),
        "vector_mean_ms": float(np.mean(vector_ms_list)),
    }
    return report


def main():
    cases = load_dataset()
    print(f"Loaded {len(cases)} cases from {DATASET_PATH}", flush=True)

    all_reports = []
    for hypo in HYPOTHESES:
        rep = evaluate_hypothesis(hypo, cases)
        all_reports.append(rep)

    out_file = Path("artifacts/research/candidate_cap_hypotheses_benchmark.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, indent=2)

    print("\n\n=================== FINAL SUMMARY ===================", flush=True)
    print(f"{'Hypothesis':<12} | {'Cap':<7} | {'Hit@1':<7} | {'Hit@3':<7} | {'Hit@10':<7} | {'MRR@10':<7} | {'Mean Latency':<12} | {'CE Mean':<10} | {'p95 Latency':<12}", flush=True)
    print("-" * 95, flush=True)
    for r in all_reports:
        cap_str = f"{r['first_cap']}/{r['second_cap']}"
        print(f"{r['hypothesis']:<12} | {cap_str:<7} | {r['hit@1']*100:5.1f}% | {r['hit@3']*100:5.1f}% | {r['hit@10']*100:5.1f}% | {r['mrr@10']:6.3f} | {r['latency_mean_ms']:8.1f} ms | {r['ce_mean_ms']:7.1f} ms | {r['latency_p95_ms']:8.1f} ms", flush=True)
    print("=====================================================", flush=True)


if __name__ == "__main__":
    main()
