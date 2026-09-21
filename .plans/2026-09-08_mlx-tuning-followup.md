# MLX tuning follow-up — 2026-09-08

## Scope and done criteria

- Continue the cached native MLX experiment only; do not change application
  source, weights, precision, packages, services, or project configuration.
- Use the pinned `mlx` `0.32.2`, `mlx-lm` `0.31.3`, Qwen3-Reranker
  `0.6B-4bit` snapshot `5f324548f1d20c2b5a450f126fc6ef2fb1126524`, and the
  unchanged two 34-document payloads.
- Keep all new raw data and runnable workload documentation under
  `docs/research/2026-09-08_mlx-tuning-followup/`; write the concise report,
  plan, and session handoff only in their same-named allowed locations.
- Preserve every failed, non-finite, timeout, and outlier record; do not drop
  documents or alter budgets.

## Method

1. Inspect the installed packaged model and MLX APIs for supported
   `BatchKVCache`, cache offsets, exact-length grouping, attention-mask, and
   position arguments. Use only inline finite calls; if an API requires custom
   code, document that boundary and test the available packaged settings
   instead of implementing an adapter.
2. Build a correctness gate before timing: compare unequal-length candidate
   batches against sequential scores for the exact same tokens, requiring
   finite 34/34 per-index scores, max delta, sorted top-10, and `0.3`
   threshold flips to be retained for every condition.
3. Adaptively screen only valid candidates, then compare finalists with the
   current optimized cap-specific baselines using at least seven randomized
   paired timed repetitions after two warmups, seed `43`, serial GPU calls,
   and caps `850` and `2400`. Separate full wall time (tokenization included),
   tokenization, and synchronized GPU time; record hashes and exact schedules.
4. Probe the packaged quantized head through its existing API only, with and
   without the requested output path where supported; report finite output and
   shape/dtype evidence without changing weights or precision.
5. Measure the existing embedding API explicitly at
   `http://127.0.0.1:8001` for five real queries, verifying current model and
   prefix. Keep startup and warm request timings distinct; do not restart it.

## Acceptance and reporting

- The result must state actual new counts, timings, correctness, outliers, and
  the best measured profile—not a theoretical maximum and not an E2E parity
  claim.
- The report must include a runnable exact workload command, unique raw/model/
  payload hashes, tokenization-boundary findings, and the reason any blocked
  batching path was blocked.