# External-runtime live evaluation — 2026-09-09

## Result

The live evaluation completed without changes to `src/`. The smoke gate passed and the requested 30-pair invocation completed. The isolated MLX vLLM reranker was stopped afterward; port `18083` is free. The existing services on ports `8001`, `18081`, and `6333` remained running and healthy.

## Service checks

| Service | Check | Result |
|---|---|---|
| External embedding | `GET http://127.0.0.1:8001/v1/models` | HTTP 200; model `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` |
| Python llama CE | `GET http://127.0.0.1:18081/health` | `{"status":"ok"}` |
| Qdrant | `GET http://127.0.0.1:6333/healthz` | `healthz check passed` |
| Isolated MLX CE | `GET http://127.0.0.1:18083/health` | HTTP 200 while running |
| Isolated MLX CE after cleanup | TCP `18083` listener | Free |

The reranker was started with the requested Metal settings, `--runner pooling`, `--max-model-len 2048`, `--max-num-seqs 1`, and the official Qwen3 reranker chat template. A two-document request through the usable Jina-compatible route `/rerank` returned:

```text
prompt_tokens=173
total_tokens=173
scores=[0.944580078125, 0.0003822948201559484]
```

This confirms the official long chat-template path rather than the short approximately-28-token path. In this vLLM build, a direct `POST /v1/rerank` returned HTTP 404, while `/rerank` succeeded; the server log explicitly advised using `/rerank`. The native Rust evaluation client nevertheless completed its rerank calls without API errors.

## Harness

Command:

```text
PYTHONPATH=src:scripts .venv/bin/python -B scripts/test_research_rust_full_eval.py
```

Result: `14` tests passed, exit code `0`.

## Smoke evaluation

The requested smoke command added two new pair slots in run `2026-09-09_external-smoke2`. Both arms completed with zero errors. The run directory already contained an earlier two-pair segment, so its final cumulative checkpoint contains four pairs.

### New smoke invocation (`2` pairs)

Primary `full1065` membership:

| Arm | Attempts | Failures | Hit@10 | MRR@10 | Latency observed | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Python | 2 | 0 | 0.5 | 0.5 | 2 | 10897.967374883592 | 15585.635167080909 |
| Rust | 2 | 0 | 0.5 | 0.5 | 2 | 10160.253416979685 | 11815.381708089262 |

### Cumulative smoke checkpoint (`4` pairs)

| Arm | Attempts | Failures | Hit@10 | MRR@10 | Latency observed | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Python | 4 | 0 | 0.75 | 0.75 | 4 | 10897.967374883592 | 16607.941875001416 |
| Rust | 4 | 0 | 0.75 | 0.55 | 4 | 8303.855958161876 | 11815.381708089262 |

The smoke gate passed, so the 30-pair evaluation was started.

## 30-pair evaluation

Command:

```text
.venv/bin/python scripts/research_rust_full_eval.py \
  --run 2026-09-09_external-run30 --max-pairs 30 --seconds 3000 \
  --embedding-runtime-mode external \
  --embedding-url http://127.0.0.1:8001/v1/embeddings \
  --qdrant-url http://127.0.0.1:6333 \
  --python-ce-url http://127.0.0.1:18081/v1/rerank \
  --rust-ce-url http://127.0.0.1:18083/v1/rerank
```

The invocation completed `30` pair slots. The run was resumable and already had prior evidence: the current segment contributed `59` new arm results (`30` Python and `29` Rust), while pair slot index `52` carried a previously interrupted Rust attempt. Therefore the invocation-level accounting is `30` Python attempts and `30` Rust attempts, with one Rust error and `29` observed Rust latencies. The final checkpoint contains `112/2132` arm results, or `56` fully paired cases cumulatively.

### New 30-pair invocation

Primary `full1065` membership:

| Arm | Attempts | Failures | Hit@10 | MRR@10 | Latency observed | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Python | 30 | 0 | 0.9666666666666667 | 0.95 | 30 | 18730.584708973765 | 93791.87325015664 |
| Rust | 30 | 1 | 0.9333333333333333 | 0.8444444444444444 | 29 | 12321.971624856815 | 120075.15912503004 |

Invocation-level paired deltas for `full1065`: Rust minus Python hit@10 `-0.03333333333333333`; Rust minus Python MRR `-0.10555555555555557`.

The one error was:

```text
index=52, arm=rust, error="Interrupted attempt; unknown latency"
```

It was a checkpoint recovery record from the prior segment, not an HTTP/API error produced by the new MLX process. All newly executed Rust rows in the current segment had `error=None`.

### New invocation by overlapping membership

| Membership | Python attempts / failures | Python hit@10 / MRR | Python p50 / p95 ms | Rust attempts / failures | Rust hit@10 / MRR | Rust p50 / p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| `WHERE78` | 1 / 0 | 1.0 / 1.0 | 8947.68733298406 / 8947.68733298406 | 1 / 0 | 1.0 / 0.3333333333333333 | 8122.437957907096 / 8122.437957907096 |
| `mech150` | 3 / 0 | 1.0 / 1.0 | 27559.475667076185 / 93791.87325015664 | 3 / 0 | 1.0 / 0.8333333333333334 | 12148.050833959132 / 86705.64720896073 |
| `mech_file229` | 4 / 0 | 1.0 / 1.0 | 25558.437291998416 / 93791.87325015664 | 4 / 0 | 1.0 / 0.7083333333333334 | 11034.964750055224 / 86705.64720896073 |

### Final cumulative checkpoint summary (`56` paired cases)

The following is the final summary stored by the harness after the invocation. Memberships overlap, so their attempt counts must not be added together.

| Membership / arm | Attempts | Failures | Hit@10 | MRR@10 | Latency observed | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `full1065` / Python | 56 | 0 | 0.9642857142857143 | 0.9553571428571429 | 56 | 20025.31079109758 | 94446.99037517421 |
| `full1065` / Rust | 56 | 1 | 0.9107142857142857 | 0.7976190476190476 | 55 | 13996.838374994695 | 119145.66733292304 |
| `WHERE78` / Python | 2 | 0 | 1.0 | 1.0 | 2 | 8947.68733298406 | 30895.442249951884 |
| `WHERE78` / Rust | 2 | 0 | 1.0 | 0.3333333333333333 | 2 | 8122.437957907096 | 88058.09654202312 |
| `mech150` / Python | 7 | 0 | 0.8571428571428571 | 0.8571428571428571 | 7 | 23188.51179187186 | 93791.87325015664 |
| `mech150` / Rust | 7 | 0 | 0.8571428571428571 | 0.6904761904761905 | 7 | 11034.964750055224 | 86705.64720896073 |
| `mech_file229` / Python | 9 | 0 | 0.8888888888888888 | 0.8888888888888888 | 9 | 23188.51179187186 | 93791.87325015664 |
| `mech_file229` / Rust | 9 | 0 | 0.8888888888888888 | 0.6111111111111112 | 9 | 11034.964750055224 | 88058.09654202312 |

## Artifacts and cleanup

Raw resumable evidence is under:

```text
artifacts/research/2026-09-07_rust-full-eval/2026-09-09_external-smoke2/
artifacts/research/2026-09-07_rust-full-eval/2026-09-09_external-run30/
```

The isolated vLLM process tree started for this evaluation was stopped. Final checks were successful: embedding HTTP 200, llama CE `{"status":"ok"}`, Qdrant `healthz check passed`, and no listener on `127.0.0.1:18083`.