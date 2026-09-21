# External runtime live evaluation — 2026-09-09

## Decision

Completed the requested live evaluation without modifying `src/`. The external embedding service, Python llama CE, and Qdrant were reused. Only the isolated vLLM reranker started for port `18083` was stopped at the end.

## Validation

- `8001/v1/models`: HTTP 200, `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`.
- `18081/health`: `{"status":"ok"}`.
- `6333/healthz`: `healthz check passed`.
- `18083/health`: HTTP 200 while the isolated MLX reranker was running.
- Two-document `/rerank` smoke: `prompt_tokens=173`, `total_tokens=173`; scores `0.944580078125` and `0.0003822948201559484`.
- Direct `/v1/rerank` returned 404 in this vLLM build; `/rerank` was the working route. The native Rust client completed evaluation requests successfully.
- Harness: `14` tests passed, exit code `0`.

## Evaluation accounting

The smoke command added `2` clean pairs. Its run directory already contained a previous two-pair segment, so the cumulative smoke checkpoint has `4` pairs. Primary `full1065` metrics for the newly added smoke pairs:

| Arm | n | failures | hit@10 | MRR | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| Python | 2 | 0 | 0.5 | 0.5 | 10897.967374883592 | 15585.635167080909 |
| Rust | 2 | 0 | 0.5 | 0.5 | 10160.253416979685 | 11815.381708089262 |

The 30-pair command completed `30` pair slots. Because the run is resumable, it added `59` new arm results (`30` Python and `29` Rust) and consumed one prior pending Rust result at index `52`. Thus the invocation-level arm totals are Python `30`, Rust `30`; Python failures `0`, Rust failures `1`, Rust observed latencies `29`. The final checkpoint has `112/2132` arm results and `56` fully paired cases cumulatively.

Primary `full1065` metrics for the 30-pair invocation:

| Arm | n | failures | hit@10 | MRR | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| Python | 30 | 0 | 0.9666666666666667 | 0.95 | 18730.584708973765 | 93791.87325015664 |
| Rust | 30 | 1 | 0.9333333333333333 | 0.8444444444444444 | 12321.971624856815 | 120075.15912503004 |

The sole error is the recovered record `index=52, arm=rust, Interrupted attempt; unknown latency`. Newly executed Rust rows in the current segment had no error. Final cumulative `full1065` metrics are Python `56/0`, hit@10 `0.9642857142857143`, MRR `0.9553571428571429`, p50/p95 `20025.31079109758/94446.99037517421` ms; Rust `56/1`, hit@10 `0.9107142857142857`, MRR `0.7976190476190476`, observed latency `55`, p50/p95 `13996.838374994695/119145.66733292304` ms.

## Cleanup result

Port `18083` is free. Final checks confirmed `8001`, `18081`, and `6333` remained healthy. Raw evidence remains in `artifacts/research/2026-09-07_rust-full-eval/2026-09-09_external-smoke2/` and `.../2026-09-09_external-run30/`.