#!/usr/bin/env python3
"""Benchmark latency optimization levers for code_diver_search_bin on Apple Silicon (MLX reranker :18083).

Specific Levers Tested:
1. Baseline: H1_cap34 (candidate-limit 34, second-pass cap 24, floor 0.3, retrieval 360, max_doc 850/2400)
2. Lever 1 (--second-pass-disable): H1_cap34 with --second-pass-disable
3. Lever 2 (--preset selective-strict): H1_cap34 with --preset selective-strict (cap 8, floor 0.15)
4. Lever 3a (--retrieval-limit 180): H1_cap34 with --retrieval-limit 180
5. Lever 3b (--retrieval-limit 120): H1_cap34 with --retrieval-limit 120
6. Lever 4a (Doc truncation: 400 chars): max-document-chars 400, second-pass-max-document-chars 1200
7. Lever 4b (Doc truncation: 200 chars): max-document-chars 200, second-pass-max-document-chars 600
8. Lever Combined (Best combo: selective-strict + retrieval-limit 180 + doc truncation 400)
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

CONFIGURATIONS = [
    {
        "name": "1. Baseline (H1_cap34)",
        "args": ["--candidate-limit", "34", "--second-pass-cap", "24", "--second-pass-floor", "0.3", "--retrieval-limit", "360", "--max-document-chars", "850", "--second-pass-max-document-chars", "2400"],
    },
    {
        "name": "2. Second-Pass Disabled (--second-pass-disable)",
        "args": ["--candidate-limit", "34", "--second-pass-disable", "--retrieval-limit", "360", "--max-document-chars", "850"],
    },
    {
        "name": "3. Preset Selective-Strict (--preset selective-strict)",
        "args": ["--candidate-limit", "34", "--preset", "selective-strict", "--retrieval-limit", "360", "--max-document-chars", "850", "--second-pass-max-document-chars", "2400"],
    },
    {
        "name": "4. Retrieval Limit 180 (--retrieval-limit 180)",
        "args": ["--candidate-limit", "34", "--second-pass-cap", "24", "--second-pass-floor", "0.3", "--retrieval-limit", "180", "--max-document-chars", "850", "--second-pass-max-document-chars", "2400"],
    },
    {
        "name": "5. Retrieval Limit 120 (--retrieval-limit 120)",
        "args": ["--candidate-limit", "34", "--second-pass-cap", "24", "--second-pass-floor", "0.3", "--retrieval-limit", "120", "--max-document-chars", "850", "--second-pass-max-document-chars", "2400"],
    },
    {
        "name": "6. CE Doc Truncation 400 chars (--max-doc 400/1200)",
        "args": ["--candidate-limit", "34", "--second-pass-cap", "24", "--second-pass-floor", "0.3", "--retrieval-limit", "360", "--max-document-chars", "400", "--second-pass-max-document-chars", "1200"],
    },
    {
        "name": "7. CE Doc Truncation 200 chars (--max-doc 200/600)",
        "args": ["--candidate-limit", "34", "--second-pass-cap", "24", "--second-pass-floor", "0.3", "--retrieval-limit", "360", "--max-document-chars", "200", "--second-pass-max-document-chars", "600"],
    },
    {
        "name": "8. Combined (selective-strict + retr 180 + doc 400)",
        "args": ["--candidate-limit", "34", "--preset", "selective-strict", "--retrieval-limit", "180", "--max-document-chars", "400", "--second-pass-max-document-chars", "1200"],
    },
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
        # Warmup query
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


def evaluate_config(cfg, cases):
    print(f"\n=======================================================", flush=True)
    print(f"Running Configuration: {cfg['name']}", flush=True)
    print(f"Args: {' '.join(cfg['args'])}", flush=True)
    print(f"=======================================================", flush=True)
    server = NativeSearchServer(cfg["args"])

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

        hit1 = any(p in expected for p in retrieved_paths[:1])
        hit3 = any(p in expected for p in retrieved_paths[:3])
        hit10 = any(p in expected for p in retrieved_paths[:10])

        hits1 += int(hit1)
        hits3 += int(hit3)
        hits10 += int(hit10)

        rr = 0.0
        for rank, p in enumerate(retrieved_paths[:10], start=1):
            if p in expected:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

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

        if (idx + 1) % 26 == 0 or idx + 1 == len(cases):
            print(f"[{idx+1}/{len(cases)}] curr MRR: {np.mean(reciprocal_ranks):.3f}, avg total: {np.mean(total_ms_list):.1f}ms, CE: {np.mean(ce_ms_list):.1f}ms (p1:{np.mean(ce_p1_ms_list):.1f}ms, p2:{np.mean(ce_p2_ms_list):.1f}ms)", flush=True)

    server.close()

    n = len(cases)
    report = {
        "name": cfg["name"],
        "args": cfg["args"],
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
    }
    return report


def main():
    cases = load_dataset()
    print(f"Loaded {len(cases)} cases from {DATASET_PATH}", flush=True)

    all_reports = []
    for cfg in CONFIGURATIONS:
        rep = evaluate_config(cfg, cases)
        all_reports.append(rep)

    out_file = Path("artifacts/research/latency_optimizations_benchmark.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_reports, f, indent=2)

    print("\n\n" + "=" * 115, flush=True)
    print(f"{'Configuration':<35} | {'H@1':<6} | {'H@3':<6} | {'H@10':<6} | {'MRR':<6} | {'Mean Total':<11} | {'Mean CE (p1+p2)':<16} | {'Vec Mean':<9} | {'p95 Total':<10}", flush=True)
    print("-" * 115, flush=True)
    for r in all_reports:
        print(f"{r['name']:<35} | {r['hit@1']*100:5.1f}% | {r['hit@3']*100:5.1f}% | {r['hit@10']*100:5.1f}% | {r['mrr@10']:5.3f} | {r['latency_mean_ms']:8.1f} ms | {r['ce_mean_ms']:6.1f} ({r['ce_p1_mean_ms']:5.1f}+{r['ce_p2_mean_ms']:4.1f}) | {r['vector_mean_ms']:6.1f} ms | {r['latency_p95_ms']:7.1f} ms", flush=True)
    print("=" * 115, flush=True)


if __name__ == "__main__":
    main()
