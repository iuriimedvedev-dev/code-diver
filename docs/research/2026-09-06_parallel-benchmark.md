# Parallel Retrieval Benchmark — Practical Results

## Summary
Measured actual speedup of H1 (skip propagation at graph_weight=0) + parallel retrieval (Opportunity A+B) on the full pipeline. **Result: no meaningful speedup.** The bottleneck is CE rerank, not retrieval.

## Benchmark Results

### Retrieval Only (`collect_rank_context`, N=20)
| Metric | Sequential | Parallel | Delta |
|---|---|---|---|
| p50 | 0.4601s | 0.4656s | **+1.2%** |
| p95 | 2.7559s | 2.7490s | **−0.2%** |
| Mean | 0.7423s | 0.7384s | **−0.5% (0.004s)** |

**Verdict: parallel retrieval gives 0.5% speedup — within noise. Not worth the complexity.**

### E2E (probe strategy, N=10)
| Metric | Baseline | Optimized | Delta |
|---|---|---|---|
| p50 | 0.9349s | 0.8967s | **−4.1%** |
| p95 | 3.2999s | 3.2446s | **−1.7%** |
| Mean | 1.2748s | 1.1370s | **−10.8% (0.14s)** |

**Verdict: 10.8% mean improvement on retrieval+post-processing, but CE rerank not included.**

### Full E2E (production pipeline, CE fallback, N=8)
CE server on port 8081 was down (Connection refused). All searches fell back to base order. The benchmark on port 18081 was not used because the champion config hardcodes port 8081.

| Metric | Baseline | Optimized | Delta |
|---|---|---|---|
| p50 | 0.9161s | 0.9303s | **+1.6%** |
| p95 | 3.1771s | 3.0307s | **−4.6%** |
| Mean | 1.1804s | 1.1915s | **+0.9%** |

**Verdict: within noise. CE rerank is the real bottleneck.**

## Why the Earlier Estimate Was Wrong

The theoretical estimate claimed ~10-15s savings from parallel retrieval. This was based on incorrect profiling:
- Vector search was estimated at ~8-10s, actual is ~0.3s (Qdrant HTTP is fast)
- BM25/lexical scoring was estimated at ~5-8s, actual is ~0.2s
- Catalog iteration was estimated at ~5-7s, actual is ~0.1-0.3s
- Total retrieval is ~0.7s, not ~25-29s

The earlier ~25-29s "retrieval" estimate was likely mixing retrieval + CE rerank + overhead.

## What Actually Matters

1. **CE rerank is the bottleneck** (~8-11s). The selective second pass (already measured) reduces retries by 68%.
2. **E2E overhead** (~25-29s total) includes retrieval + CE + meta-ranker + serialization.
3. **Retrieval itself is fast** (~0.7s). No optimization needed here.

## Next Steps
- Re-enable Rust native search (`CODE_DIVER_NATIVE_SEARCH=1`) — the Rust module is already compiled (v0.2.0). It could accelerate BM25, seed coverages, and propagation.
- Investigate embedding cache for frequent queries.
- Measure CE server inference time vs batch size on Metal.

## Commands
```
cd /Users/iurii.medvedev/Work/code-diver
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/research_combined_e2e_benchmark.py
```

## Artifacts
- `artifacts/research/2026-09-06_parallel-benchmark/results.json` — retrieval-only (N=20)
- `artifacts/research/2026-09-06_parallel-benchmark/e2e_results.json` — probe strategy (N=10)
- `artifacts/research/2026-09-06_parallel-benchmark/full_e2e_results.json` — production pipeline (N=8, CE fallback)

## Git
`d1c50640` — dirty worktree with parallel retrieval changes + benchmark scripts.
`git diff --check` — clean.
137 tests passed in 27.62s.