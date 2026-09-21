# MLX search serving and end-to-end feasibility — 2026-09-08

## Scope

Determine whether a ready-made upstream MLX/vLLM-Metal pooling service can serve
the pinned local `mlx-community/Qwen3-Reranker-0.6B-4bit` snapshot
`5f324548f1d20c2b5a450f126fc6ef2fb1126524` with a verified pairwise rerank
contract, then evaluate it end to end against the unchanged H91a Python CE
baseline. Do not modify application source, the root `.venv`, `uv.lock`, or
existing services (`18081`, `8001`, `6333`); do not run unsafe benchmark
preparation or restart/kill unrelated processes.

## Bounded method

1. Inspect the upstream pooling documentation and the installed isolated
   runtime before installing anything. Use only `.tmp/mlx-search-runtime` for
   dependencies and preserve `HOME` and the existing MLX cache.
2. Prefer a supported packaged server/configuration. Require exact model
   identity, the documented Qwen3 sequence-classification overrides, a free
   IPv4 listen port, and a real HTTP smoke response. Record whether the
   response is `/v1/rerank` with probability/index fields or only a pooling
   classification score; a mismatch is a concrete blocker, not an adapter
   opportunity.
3. If the contract is compatible, run the existing safe evaluator with truthful
   MLX/Rust endpoint overrides: two smoke pairs, then at least 30 distinct
   paired queries, unchanged retrieval `360`, candidate/CE budget `34`, and the
   old H91a meta model. Keep failures in the denominator; report top-10 hit,
   MRR, quality, and latency p50/p95 with initialization separated.
4. If the contract is not compatible or no supported server exists, stop without
   custom source/adapters and document the exact missing interface and smallest
   required implementation scope.

## Done criteria

The report contains exact upstream source/commands, installed versions, model
revision and prompt/weights identity, actual POST schema and measured outputs,
or a reproducible specific blocker. No claim of independent holdout quality is
made for the currently exposed datasets.