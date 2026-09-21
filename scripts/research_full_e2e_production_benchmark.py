#!/usr/bin/env python3
"""Full E2E benchmark: champion vs optimizations (H1 + parallel).
Uses the actual production CrossEncoderRerankRetrievalStrategy with CE rerank.
Measures wall time of the FULL search pipeline including CE rerank.
"""
import json, time, statistics, sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def load_queries(n=8):
    dataset_path = "datasets/intellij_eval_1000.answer_sets.jsonl"
    queries = []
    with open(dataset_path) as f:
        for i, line in enumerate(f):
            if i >= n: break
            entry = json.loads(line)
            queries.append({"id": entry.get("id", f"q{i}"), "query": entry.get("query", "")})
    return queries


def run_production_e2e(queries, label):
    """Run full production E2E pipeline (including CE rerank) and measure wall time."""
    from pathlib import Path
    from code_diver.config import ConfigLoader
    from code_diver.env import EnvFileLoader
    from code_diver.cli import make_vector_store, make_embedding_provider, make_retrieval_strategy
    
    config_path = Path("configs/intellij/intellij-h91a-champion.yml")
    config = ConfigLoader().load(config_path)
    EnvFileLoader().load(config.env_file.path, config.env_file.override)
    
    store = make_vector_store(config, progress=False)
    if not store.exists():
        raise RuntimeError("index not found")
    provider = make_embedding_provider(config, store.metadata())
    strategy = make_retrieval_strategy(config, provider, store)
    
    print(f"  Strategy type: {type(strategy).__name__}")
    
    # Warmup
    print(f"  Warming up ({len(queries[:2])} queries)...")
    for q in queries[:2]:
        try: strategy.search(q["query"], 10)
        except Exception as e: print(f"  Warmup error: {e}")
    
    # Benchmark
    print(f"  Running {len(queries)} full E2E searches (with CE rerank)...")
    times = []
    for i, q in enumerate(queries):
        t0 = time.perf_counter()
        try:
            result = strategy.search(q["query"], 10)
            dt = time.perf_counter() - t0
            times.append(dt)
            print(f"    {i+1}/{len(queries)}: {q['id']} = {dt:.3f}s", flush=True)
        except Exception as e:
            print(f"    Error {i} ({q['id']}): {e}")
    
    store.close()
    
    if not times: return None
    times.sort()
    return {
        "label": label, "n": len(times),
        "p50_s": round(statistics.median(times), 4),
        "p95_s": round(times[int(len(times)*0.95)], 4) if len(times)>=20 else round(times[-1], 4),
        "mean_s": round(statistics.mean(times), 4),
        "min_s": round(times[0], 4), "max_s": round(times[-1], 4),
        "stdev_s": round(statistics.stdev(times), 4) if len(times)>1 else 0,
    }


def main():
    print("="*60)
    print("FULL E2E PRODUCTION BENCHMARK (with CE rerank)")
    print("="*60)
    
    queries = load_queries(8)
    git_rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()[:12]
    print(f"Queries: {len(queries)}, Git: {git_rev}")
    
    results = {}
    
    # Run 1: Optimized (H1 + parallelretrieval)
    print("\n--- OPTIMIZED (H1 + Parallel, current code) ---")
    results["optimized"] = run_production_e2e(queries, "optimized")
    if results["optimized"]:
        print(f"  p50={results['optimized']['p50_s']}s  p95={results['optimized']['p95_s']}s  mean={results['optimized']['mean_s']}s")
    
    # Stash changes to get sequential baseline
    print("\n--- Stashing parallel changes...")
    subprocess.run(["git", "stash", "--",
        "src/code_diver/strategies/hybrid_retrieval_strategy.py",
        "src/code_diver/strategies/graph_file_retrieval_strategy.py"],
        capture_output=True)
    
    # Run 2: Baseline (sequential, no H1)
    print("\n--- BASELINE (sequential, no H1) ---")
    results["baseline"] = run_production_e2e(queries, "baseline")
    if results["baseline"]:
        print(f"  p50={results['baseline']['p50_s']}s  p95={results['baseline']['p95_s']}s  mean={results['baseline']['mean_s']}s")
    
    # Restore
    print("\n--- Restoring parallel changes...")
    subprocess.run(["git", "stash", "pop"], capture_output=True)
    
    # Results
    output = {
        "git_revision": git_rev,
        "timestamp": time.time(),
        "queries": [q["id"] for q in queries],
        **results,
    }
    
    if results.get("baseline") and results.get("optimized"):
        b, o = results["baseline"], results["optimized"]
        speedup = {
            "mean_pct": round((b["mean_s"] - o["mean_s"]) / b["mean_s"] * 100, 1),
            "p50_pct": round((b["p50_s"] - o["p50_s"]) / b["p50_s"] * 100, 1),
            "p95_pct": round((b["p95_s"] - o["p95_s"]) / b["p95_s"] * 100, 1),
            "absolute_savings_mean_s": round(b["mean_s"] - o["mean_s"], 4),
        }
        output["speedup"] = speedup
        print(f"\n{'='*60}")
        print(f"COMBINED SPEEDUP (all optimizations, FULL pipeline):")
        print(f"  Mean: {speedup['mean_pct']}% ({speedup['absolute_savings_mean_s']}s per query)")
        print(f"  p50:  {speedup['p50_pct']}%")
        print(f"  p95:  {speedup['p95_pct']}%")
        print(f"  Baseline:  p50={b['p50_s']}s  mean={b['mean_s']}s")
        print(f"  Optimized: p50={o['p50_s']}s  mean={o['mean_s']}s")
        print(f"{'='*60}")

    out = "artifacts/research/2026-09-06_parallel-benchmark/full_e2e_results.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()