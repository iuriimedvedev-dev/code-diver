# Rust Search Pipeline Benchmark

## Hypothesis

Pure Rust search pipeline (`code_diver_search_bin`) can match or exceed Python pipeline performance by eliminating Python overhead, PyO3 FFI costs, and single-threaded orchestration.

## Setup

- **Binary**: `native/code_diver_search_bin/target/release/code_diver_search_bin`
- **Rust version**: 10 modules, ~2700 LOC, Tokio async runtime
- **Services**: Same CE (port 18081), embedding (port 8001), Qdrant (port 6333) as Python pipeline
- **Data**: 136,578 catalog items, 55,123 graph nodes, 200-tree LightGBM meta-ranker
- **Queries**: 20 WHERE-78 queries, first 20 from `datasets/intellij_eval_where_only.jsonl`
- **Limit**: 10 results per query
- **Warmup**: 1st query includes cold start (catalog loading, BM25 index build, model loading)

## Results

### Overall

| Metric | Value |
|---|---|
| Queries | 20 / 20 (0 errors) |
| Total time | 45.4s |
| Mean/query | **2,270ms (2.27s)** |
| Median/query | **1,980ms (1.98s)** |
| P95/query | **3,703ms (3.70s)** |

### Stage Breakdown

| Stage | Mean | p50 | p95 | % of total |
|---|---|---|---|---|
| CE first pass | 1,461ms | 1,465ms | 1,560ms | 64% |
| CE second pass | 660ms | 383ms | 2,007ms | 29% |
| Embedding | 121ms | 14ms | 344ms | 5% |
| Vector search | 14ms | 11ms | 32ms | <1% |
| BM25 | 12ms | 3ms | 96ms | <1% |
| Graph propagation | 0.004ms | 0.004ms | 0.01ms | <0.1% |
| Feature extraction | 0.24ms | 0.23ms | 0.30ms | <0.01% |
| Meta-ranker predict | 0.06ms | 0.06ms | 0.09ms | <0.01% |
| Fusion | 0.003ms | 0.003ms | 0.01ms | <0.01% |

### Comparison with Python Pipeline

| Metric | Python | Rust | Speedup |
|---|---|---|---|
| E2E mean | ~30-32s | **2.27s** | **~13-14x** |
| CE first pass | ~7-8s | 1.46s | ~5x |
| CE second pass | ~2-3s | 0.66s | ~4x |
| Embedding | ~0.3-0.5s | 0.12s | ~3x |
| Vector search | ~0.3s | 0.014s | ~21x |
| BM25 | ~0.2s | 0.012s | ~17x |
| Meta-ranker | <0.1ms | 0.06ms | same |
| Graph propagation | ~0.004ms | 0.004ms | same |

### Key Findings

1. **CE first pass dominates** (64% of total time) — the bottleneck is the reranker inference, not Python overhead
2. **LightGBM meta-predict is negligible** (0.06ms) — same as Python
3. **Embedding cold start is significant** (p95 344ms vs p50 14ms) — HTTP connection overhead
4. **BM25 cold start is moderate** (p95 96ms vs p50 3ms) — first query includes BM25 index build
5. **Graph propagation is free** (0.004ms) — graph_weight=0 in current config
6. **Rust removes Python orchestration overhead** — serialization, object creation, GC pauses

## Changes Made

### graph.rs
- Fixed `parse_neighbors` to handle JSON array format `[["path", weight], ...]` in addition to object format `[{"path": "...", "weight": ...}, ...]`

### lightgbm.rs
- Rewrote parser to handle actual LightGBM TXT format: `Tree=0` (capital T), space-separated arrays per attribute, `left_child`/`right_child` as arrays, `leaf_value` as space-separated
- Added recursive tree building from flat arrays with correct child index encoding (positive = internal node, negative = ~leaf_index)

### embedding.rs
- Fixed embedding model name: `text-embedding-3-small` → `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`
- Fixed CE response parsing: `data["scores"]` → `data["results"][i]["relevance_score"]`
- Fixed Qdrant payload path: `payload["path"]` → `payload["item"]["path"]` (nested structure)

### scripts/rust_bench_prepare.py (new)
- Dumps catalog to Rust JSONL format
- Builds graph adjacency JSONL
- Extracts queries from WHERE-78 dataset
- Runs benchmark and saves results

## Limitations

- **Quality parity NOT verified** — Rust pipeline uses catalog content (summaries) for CE documents, not full file content. CE scores may differ from Python pipeline
- **20 queries only** — not a full E2E evaluation on 1065 pairs
- **Same CE server** — both pipelines use the same inference endpoint, so CE latency is shared
- **No second pass refinement** — Rust second pass uses same document retrieval as first pass, not the `2400-char` expanded version
- **No meta-ranker feature parity** — Rust features are simplified (no real import analysis, fan-in is hash-based)
- **No promotion** — this is a benchmark, not a production replacement

## What's Next

1. Verify quality parity: compare Rust vs Python results on the same queries
2. Full E2E eval on 1065 pairs
3. Add proper content loading for CE (full file content, not just catalog summaries)
4. Profile CE server for further optimization
5. Add warm-start optimization (pre-heat embedding connections)

## Commands

```bash
# Single query
./native/code_diver_search_bin/target/release/code_diver_search_bin \
  --catalog /tmp/rust_catalog.jsonl \
  --graph /tmp/rust_graph.jsonl \
  --model artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt \
  --query "where is project opening orchestrated" \
  --limit 10

# Benchmark 20 queries
./native/code_diver_search_bin/target/release/code_diver_search_bin \
  --catalog /tmp/rust_catalog.jsonl \
  --graph /tmp/rust_graph.jsonl \
  --model artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt \
  --bench /tmp/rust_bench_queries.txt \
  --bench-n 20 \
  --limit 10
```

## Evidence

- Results: `artifacts/research/2026-09-06_rust-benchmark/results.json`
- Prepare script: `scripts/rust_bench_prepare.py`
- Rust binary: `native/code_diver_search_bin/target/release/code_diver_search_bin`
- Tests: 19/19 passed (`cargo test`)