# MLX latency and bounded search evaluation — 2026-09-08

## Scope and constraints

- Measurement-only stretch: no application source, scripts, adapters, packages,
  model weights, service configuration, cache purge, service restart, or
  unrelated-process termination.
- Preserve prior evidence. Do not relabel or repeat the 2026-09-07 Rust full
  evaluation or the earlier MLX benchmark as new evidence.
- Write the report to `docs/research/2026-09-08_mlx-latency-eval.md`, durable
  raw evidence only to the new same-named artifact directory, and record exact
  commands and decisions in the same-named `.session` handoff.

## Definition of done

1. Establish endpoint health and identity without treating health as warmth;
   record supported, unprivileged memory-pressure snapshots.
2. Determine whether `scripts/keep_services_warm.py` can safely run only the
   embedder at explicit `127.0.0.1:8001`. Because the current helper always
   starts both embedder and reranker threads, do not invoke its default if it
   cannot be isolated. If isolation is impossible, run only bounded direct
   embedder API requests as an explicitly periodic mitigation and state that
   this is not helper-script verification.
3. Run at least three randomized paired blocks per condition, with 60 seconds
   idle before each first query, a real query matching the current embedder
   prefix/model, an immediate second novel query, and a 90-second per-request
   timeout. Retain every success, timeout, and error; stop any owned helper
   after each block and never kill unrelated processes.
4. Capture dimensions `1024 x 1024`, finite identity, wall/request dimensions,
   and memory-pressure observations where supported. Distinguish service health,
   workload idle, and global idle in the raw records.
5. Run a fresh bounded serial Rust search baseline using the existing safe
   harness, 30 distinct deterministic diagnostic dataset pairs, direct IPv4
   runtime overrides where supported, CE candidate budget `34`, retrieval
   limit `360`, and keepwarm OFF. Preserve the manifest and all result rows.
   Report failure-inclusive Hit@10, MRR@10, request-wall p50/p95, startup
   separately, and existing internal stages when present. Do not claim MLX
   end-to-end integration; search remains llama CE.
6. Run the existing Rust harness unit tests and any directly relevant existing
   research tests; do not add source tests or alter assertions.

## Planned execution order

1. Create the new artifact directory and freeze this plan before live runs.
2. Inspect service health, models, supported API behavior, current git/source
   identity, and safe memory-pressure commands.
3. Execute the latency blocks serially on the GPU, retaining immutable raw
   JSON/JSONL files and exact shell invocations. Use bounded inline requests;
   no new script or package.
4. Execute the 30-pair Rust baseline serially after latency trials, with a fresh
   unique run name and truthful IPv4 manifest. Never resume or mutate old runs.
5. Run tests and calculate descriptive small-sample percentiles from retained
   rows. Write the concise report and session handoff with actual counts,
   errors, metrics, hashes, causal limits, and artifact paths.

## Stop and safety rules

- If endpoint identity, prefix, route override, or query isolation cannot be
  verified, record the block and do not substitute a harmful default.
- Do not use privileged commands, service management, cache deletion, git
  stash/reset/restore, or broad process cleanup.
- A failed or timed-out request remains in the denominator and raw evidence.
- A 30-pair result is bounded descriptive evidence, not an independent holdout
  or a claim about MLX end-to-end latency.