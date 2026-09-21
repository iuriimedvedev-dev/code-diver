# MLX latency and bounded search evaluation — 2026-09-08

## Decision

No application source or existing evaluation script was changed. The helper
`scripts/keep_services_warm.py` was not run because its two unconditional
threads cannot isolate the embedder from CE/KnotGate. Direct embedder API
requests were used for the ON condition and are explicitly not helper-script
verification.

## Completed evidence

- Frozen plan: `.plans/2026-09-08_mlx-latency-eval.md`.
- Preflight: all required endpoints returned HTTP 200; model identities were
  embedder `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` and CE
  `Qwen3-Reranker-0.6B-Q4_K_M.gguf`.
- Latency: 3 OFF and 3 ON randomized blocks, each with 60 seconds controlled
  workload idle, real first query, immediate novel second query, and 90-second
  request timeout. All 12 real requests and 90 ON warm requests succeeded with
  finite 1024-dimensional vectors. OFF first p50/p95 `2075.0/2191.7 ms`; ON
  `26.1/27.8 ms`. Immediate second p50/p95 were `13.8/14.1` and
  `15.7/16.7 ms`.
- Baseline: fresh `bounded-20260908T140300Z`, 30 distinct pairs, 60 arm
  attempts, zero failures, CE candidate `34`, retrieval `360`, serial GPU,
  keepwarm OFF. `full1065` Python `Hit@10/MRR=0.966667/0.966667`, Rust
  `0.900000/0.776389`; request p50/p95 Python `8041.0/15462.6 ms`, Rust
  `6614.8/9308.8 ms`. Startup Python/Rust `1775.71/5697.28 ms`; existing Rust
  internal `total_ms` p50/p95 `6614.3/9308.6 ms`.
- Tests: `scripts/test_research_rust_full_eval.py` `4/4`; relevant pytest
  modules `25/25`.

## Limitations and next steps

Global idle was not observable with the permitted unprivileged commands, so the
latency result is a bounded descriptive observation rather than a causal proof
of macOS memory eviction. Search remains llama CE; no MLX E2E result is claimed.
The old evidence under `2026-09-07_rust-full-eval` remains untouched; new
copies and the rejected direct-embedder manifest are under the new artifact
directory with hashes listed in the report.