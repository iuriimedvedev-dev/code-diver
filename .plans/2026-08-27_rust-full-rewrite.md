# Rust Full Rewrite — Vector cosine similarity + comparison

## Objective
Port the last remaining hot path — vector cosine similarity search — to Rust, then run latency comparison vs jbcontext.

## Context
- BM25, fusion, coverage, propagation, expansion, seed loop → already Rust
- Seed loop is 8x slower in Rust (PyO3 bridge overhead) — NOT worth porting
- **Real bottleneck**: JSON cosine similarity (`json_vector_store._search_items`) — brute-force dot product over 68k items × 136k vectors
- Current latency: 5.5-8.9s/query vs jbcontext 1.4-1.6s (5-6x slower)

## Plan

### Step 1: `vector_math.rs` — Rust native dot/normalize/search_flat
- `normalize(vector: &[f64]) -> Vec<f64>` — L2 normalization
- `dot(left: &[f64], right: &[f64]) -> f64` — dot product
- `search_flat(query, flat_f32, offsets, limit)` — batch cosine over f32 flat array
- `search_flat_f64(query, flat_f64, offsets, limit)` — batch cosine over f64 flat array
- Unit tests for all functions

### Step 2: PyO3 bindings in `lib.rs`
- `normalize_py`, `dot_py`
- `search_flat_py`, `search_flat_f64_py`

### Step 3: Python dual-path bridge
- `native_search.py` — `try_normalize`, `try_dot`, `try_search_flat`, `try_search_flat_f64`
- `math_utils.py` — dual-path for dot/normalize
- `json_vector_store.py` — dual-path for `_search_items`
- `in_memory_vector_store.py` — dual-path for `search`

### Step 4: Build + test + benchmark
- `cargo test --no-default-features`
- `maturin develop`
- `pytest tests/unit/`
- Benchmark: n=68k items, d=768, measure ms/query

### Step 5: Compare with jbcontext
- Re-run eval on 4 datasets (WHERE-79, Synthetic 200, Multifile 60, Multifile 100)
- Same intellij-community rev `693e76f0a37a`
- Measure latency improvement
- Report full comparison table

## Success criteria
- Rust cosine search ≥ 2x faster than Python on same data
- Latency/query drops from 5.5-8.9s to <3s
- Full comparison table vs jbcontext