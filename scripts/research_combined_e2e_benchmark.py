#!/usr/bin/env python3
"""Combined benchmark: measure ALL optimizations together.
Tests:
1. Baseline (sequential code, no H1 skip propagation)
2. H1 only (skip propagation at graph_weight=0)
3. H1 + Parallel (all current optimizations)
Measures full E2E search time including CE rerank via CrossEncoderRerankRetrievalStrategy.
"""
import json, time, statistics, sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def load_queries(n=10):
    dataset_path = "datasets/intellij_eval_1000.answer_sets.jsonl"
    queries = []
    with open(dataset_path) as f:
        for i, line in enumerate(f):
            if i >= n: break
            entry = json.loads(line)
            queries.append({"id": entry.get("id", f"q{i}"), "query": entry.get("query", "")})
    return queries


def run_full_e2e_bench(queries, label):
    """Run full E2E search (including CE rerank) and measure wall time."""
    from pathlib import Path
    from replay_pool_recall import load_config, build_probe_strategy
    config_path = "configs/intellij/intellij-h91a-champion.yml"
    
    config = load_config(Path(config_path))
    strategy, _, store = build_probe_strategy(config)
    
    # Warmup
    print(f"  Warming up...")
    for q in queries[:2]:
        try: strategy.search(q["query"], 10)
        except: pass
    
    # Benchmark
    print(f"  Running {len(queries)} full E2E searches...")
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
        "per_query": [round(t, 4) for t in times],
    }


def main():
    print("="*60)
    print("COMBINED E2E BENCHMARK")
    print("="*60)
    
    queries = load_queries(10)
    git_rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()[:12]
    print(f"Queries: {len(queries)}, Git: {git_rev}")
    
    results = {}
    
    # Run 1: Parallel (current code - H1 + parallel)
    print("\n--- OPTIMIZED (H1 + Parallel, current code) ---")
    results["optimized"] = run_full_e2e_bench(queries, "optimized")
    if results["optimized"]:
        print(f"  p50={results['optimized']['p50_s']}s  p95={results['optimized']['p95_s']}s  mean={results['optimized']['mean_s']}s")
    
    # Stash all changes to get pure sequential baseline (no H1, no parallel)
    print("\n--- Stashing all changes...")
    subprocess.run(["git", "stash", "--",
        "src/code_diver/strategies/hybrid_retrieval_strategy.py",
        "src/code_diver/strategies/graph_file_retrieval_strategy.py"],
        capture_output=True)
    
    # Run 2: Sequential baseline (no H1, no parallel)
    print("\n--- BASELINE (sequential, no H1) ---")
    results["baseline"] = run_full_e2e_bench(queries, "baseline")
    if results["baseline"]:
        print(f"  p50={results['baseline']['p50_s']}s  p95={results['baseline']['p95_s']}s  mean={results['baseline']['mean_s']}s")
    
    # Restore parallel
    print("\n--- Restoring parallel changes...")
    subprocess.run(["git", "stash", "pop"], capture_output=True)
    
    # Compute combined speedup
    output = {
        "git_revision": git_rev,
        "timestamp": time.time(),
        "queries": [q["id"] for q in queries],
        **results,
    }
    
    if results.get("baseline") and results.get("optimized"):
        b, o = results["baseline"], results["optimized"]
        speedup_mean = round((b["mean_s"] - o["mean_s"]) / b["mean_s"] * 100, 1)
        speedup_p50 = round((b["p50_s"] - o["p50_s"]) / b["p50_s"] * 100, 1)
        speedup_p95 = round((b["p95_s"] - o["p95_s"]) / b["p95_s"] * 100, 1)
        output["speedup"] = {
            "mean_pct": speedup_mean,
            "p50_pct": speedup_p50,
            "p95_pct": speedup_p95,
            "absolute_savings_mean_s": round(b["mean_s"] - o["mean_s"], 4),
        }
        print(f"\n{'='*60}")
        print(f"COMBINED SPEEDUP (all optimizations):")
        print(f"  Mean: {speedup_mean}% ({output['speedup']['absolute_savings_mean_s']}s per query)")
        print(f"  p50:  {speedup_p50}%")
        print(f"  p95:  {speedup_p95}%")
        print(f"{'='*60}")

    out = "artifacts/research/2026-09-06_parallel-benchmark/e2e_results.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()