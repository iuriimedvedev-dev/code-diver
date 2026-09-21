# MLX search recovery — 2026-09-09

## Scope

- Re-test only the cached `vllm-metal` MLX reranker on owned port `18083`.
- Do not change application source, adapters, packages, weights, templates, or
  unrelated services. Preserve all prior artifacts.
- Use the pinned Qwen3 reranker snapshot and official template from the
  2026-09-08 diagnosis.

## Safety gate

1. Probe current IPv4 embedding `8001`, llama CE `18081`, and Qdrant `6333`;
   each request is bounded to 30 seconds and gets one warm follow-up only after
   a successful cold request.
2. Capture `memory_pressure` and `vm_stat` before and after the probes and
   after any owned MLX smoke. Do not infer thrashing from swap occupancy alone.
3. Launch only the owned MLX endpoint, with explicit numeric memory allocation,
   one sequence, and bounded scheduler token budgets. Stop it promptly on a
   timeout, semantic failure, or renewed pressure.

## Validation

- First verify the official-template two-document semantic result and a fixed
  34-document short/long payload within the bounded gate.
- Verify the evaluator’s in-memory IPv4 override and frozen manifest before
  bulk work; the manifest must record `127.0.0.1` for both CE URLs, embedding,
  and Qdrant while retaining retrieval `360`, CE `34`, and result `10`.
- If stable, run the existing evaluator tests, the new frozen two-case smoke,
  then the requested 30 distinct paired cases with failure-inclusive Hit@10
  and MRR@10, separate initialization and request p50/p95, and exposed-data
  counts. Stop after the experiment and report exact commands, settings,
  hashes, limits, and measured outcomes.

## Blocker rule

If the existing module API cannot truthfully override all runtime routes in
memory without bypassing guards or changing application code, stop before bulk
evaluation and document the concrete blocker.