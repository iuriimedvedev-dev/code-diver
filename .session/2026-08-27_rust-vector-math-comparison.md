# Rust vector math + numpy optimization + jbcontext comparison

## What was done

### Rust: `vector_math.rs` module
- `normalize` — L2 normalization (also used in `math_utils.py` via native dual-path)
- `dot` — dot product (also used in `math_utils.py` via native dual-path)
- `search_flat` / `search_flat_f64` — batch cosine similarity over flat f32/f64 arrays
- 12 unit tests, all passing
- PyO3 bindings: `normalize_py`, `dot_py`, `search_flat_py`, `search_flat_f64_py`
- Native module version bumped to 0.2.0

### Python dual-path wiring
- `math_utils.py`: `normalize`/`dot` use native when available, Python fallback
- `native_search.py`: `try_normalize`, `try_dot`, `try_search_flat` bridge functions
- `json_vector_store.py`: `_search_items` tries native path first, falls back to Python

### Key discovery: numpy is 1341x faster than Python loop, Rust is 0.9x Python
Benchmark on 68k items × 768 dim:
- Python loop: 3.2s
- Rust native (PyO3): 3.5s (0.9x — bridge overhead)
- **NumPy `@` operator: 2.4ms (1341x)**

The numpy path was added to `JsonVectorStore._search_items` for both full-search and kind-filtered search.

### Jbcontext comparison (4 datasets, intellij-community rev 693e76f0a37a)

| Dataset | n | recall@10 CD | recall@10 JB | Δ | MRR CD | MRR JB | Δ |
|---|---|---|---|---|---|---|---|
| WHERE-79 | 79 | 0.528 | 0.682 | -0.154 | 0.289 | 0.351 | -0.062 |
| Synthetic 200 | 200 | 0.820 | 0.895 | -0.075 | 0.612 | 0.680 | -0.068 |
| Multifile 60 | 60 | 0.581 | 0.517 | **+0.064** | 0.571 | 0.594 | -0.023 |
| Multifile 100 | 102 | 0.494 | 0.541 | -0.048 | 0.481 | 0.555 | -0.075 |

Quality unchanged vs previous code-diver (Δ < 0.01 on all metrics).

### Latency regression
- Current: 14.3-16.0s/query (vs 7.2s/query previously)
- Root cause: the bottleneck is Qdrant server-side search, not Python cosine similarity
- The numpy/Rust optimization for `JsonVectorStore._search_items` doesn't help because the actual deployment uses `QdrantVectorStore`
- H52 collection has 136k points, which may be slower to search on Qdrant side

## What's still Python-only
- CLI, eval, config loading — no benefit from Rust
- Embedding/Reranker HTTP calls — external services
- Qdrant client — server-side search
- Graph-file orchestration — Python-only
- Hybrid retrieval strategy — Python-only (RRF, file-vote)
- Symbol-match scorer — needs item metadata

## Next
- Investigate latency regression: is Qdrant server overloaded or H52 collection slower?
- 1065 eval still pending (needs 120min window)
- Champion YAML not flipped