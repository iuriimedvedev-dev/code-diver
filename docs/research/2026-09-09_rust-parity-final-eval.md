# Rust parity final evaluation — 2026-09-09

## Result

The rebuilt Rust release binary was evaluated against the Python H91a baseline using the isolated MLX Metal reranker on the M3 Max. The two-pair smoke gate completed without failures, followed by the requested 30 distinct pairs. The candidate did not reach parity with Python in this run: Rust hit@10 and MRR were lower, and its 30-pair end-to-end p50 and p95 wall times were higher.

The evaluation did not restart or kill the pre-existing embedding, Python CE, or Qdrant services. Only the MLX process tree started for port `18083` was stopped after the run.

## Runtime and binary validation

| Component | Check | Result |
|---|---|---|
| Embedding | `GET http://127.0.0.1:8001/v1/models` | HTTP `200`; existing service reused |
| Python H91a CE | `GET http://127.0.0.1:18081/health` | HTTP `200`; existing service reused |
| Qdrant | `GET http://127.0.0.1:6333/healthz` | HTTP `200`; existing service reused |
| MLX CE | `GET http://127.0.0.1:18083/health` | HTTP `200` while running |
| MLX CE cleanup | listener on `18083` after evaluation | Free |
| Native binary | `shasum -a 256 native/code_diver_search_bin/target/release/code_diver_search_bin` | `28161f0834436006cd838b3f5ab740f34c3aa6db5fcca0d60d6c1d2b19f2a0de` |

The MLX server used the requested Metal settings, Qwen3 reranker snapshot, official chat template, pooling runner, and constrained single-sequence configuration. The two-document probe and all evaluation rerank requests completed successfully.

## Commands and evidence

Smoke run:

```text
.venv/bin/python scripts/research_rust_full_eval.py \
  --run 2026-09-09_parity-smoke2 --max-pairs 2 --seconds 3000 \
  --embedding-runtime-mode external \
  --embedding-url http://127.0.0.1:8001/v1/embeddings \
  --qdrant-url http://127.0.0.1:6333 \
  --python-ce-url http://127.0.0.1:18081/v1/rerank \
  --rust-ce-url http://127.0.0.1:18083/v1/rerank
```

Thirty-pair run:

```text
.venv/bin/python scripts/research_rust_full_eval.py \
  --run 2026-09-09_parity-run30 --max-pairs 30 --seconds 3000 \
  --embedding-runtime-mode external \
  --embedding-url http://127.0.0.1:8001/v1/embeddings \
  --qdrant-url http://127.0.0.1:6333 \
  --python-ce-url http://127.0.0.1:18081/v1/rerank \
  --rust-ce-url http://127.0.0.1:18083/v1/rerank
```

The smoke summary is stored in `artifacts/research/2026-09-07_rust-full-eval/2026-09-09_parity-smoke2/summary-1788975153443029000.json`. The 30-pair summary is stored in `artifacts/research/2026-09-07_rust-full-eval/2026-09-09_parity-run30/summary-1788975335772011000.json`.

## Smoke gate

The smoke run completed two Python and two Rust attempts with zero failures. The primary `full1065` membership was:

| Arm | Attempts | Failures | Hit@10 | MRR@10 | p50 wall time | p95 wall time |
|---|---:|---:|---:|---:|---:|---:|
| Python | 2 | 0 | `1.000000` | `1.000000` | `12,521.71 ms` | `12,573.00 ms` |
| Rust + MLX | 2 | 0 | `0.500000` | `0.250000` | `7,219.48 ms` | `8,349.22 ms` |

The smoke gate therefore passed operationally, and Rust was faster on these two requests: p50 was `42.34%` lower and p95 was `33.59%` lower than Python. The sample is too small to represent the final quality or latency result.

## Thirty-pair quality comparison

The primary `full1065` membership contains 30 paired Python/Rust cases, with zero request failures on either arm.

| Arm | Attempts | Failures | Hit@10 | MRR@10 | p50 wall time | p95 wall time |
|---|---:|---:|---:|---:|---:|---:|
| Python H91a | 30 | 0 | `0.9666666667` | `0.9666666667` | `21,907.73 ms` | `94,266.22 ms` |
| Rust + MLX | 30 | 0 | `0.7333333333` | `0.6111111111` | `23,741.84 ms` | `125,080.77 ms` |
| Rust minus Python | — | — | `-0.2333333333` | `-0.3555555556` | `+1,834.11 ms` | `+30,814.55 ms` |

Rust was `8.37%` slower at p50 and `32.69%` slower at p95 for the full end-to-end request wall time. These measurements include retrieval, candidate processing, cross-encoder calls, and result handling, not just isolated model inference.

## Quality delta versus pre-parity baseline

The requested prior comparison is `2026-09-09_external-run30`, where Rust recorded hit@10 `0.9333333333` and MRR `0.8444444444`.

| Rust evaluation | Hit@10 | MRR@10 | p50 wall time | p95 wall time |
|---|---:|---:|---:|---:|
| Before parity fixes: `external-run30` | `0.9333333333` | `0.8444444444` | `12,321.97 ms` | `120,075.16 ms` |
| After parity fixes: `parity-run30` | `0.7333333333` | `0.6111111111` | `23,741.84 ms` | `125,080.77 ms` |
| After minus before | `-0.2000000000` | `-0.2333333333` | `+11,419.87 ms` | `+5,005.61 ms` |

The rebuilt candidate is therefore `20.00` percentage points lower in hit@10 and `23.33` percentage points lower in MRR than the supplied baseline. Relative to the baseline, hit@10 decreased `21.43%` and MRR decreased `27.63%`; p50 latency increased `92.68%` and p95 latency increased `4.17%`.

## M3 Max MLX speedup assessment

MLX Metal was operational and handled the Rust rerank requests on the M3 Max. The two-pair smoke sample showed a clear latency improvement, but the statistically more useful 30-pair run did not confirm an end-to-end speedup:

- Smoke: Rust p50 was `7,219.48 ms` versus Python `12,521.71 ms` (`42.34%` faster); Rust p95 was `8,349.22 ms` versus Python `12,573.00 ms` (`33.59%` faster).
- Thirty pairs: Rust p50 was `23,741.84 ms` versus Python `21,907.73 ms` (`8.37%` slower); Rust p95 was `125,080.77 ms` versus Python `94,266.22 ms` (`32.69%` slower).

Conclusion: the MLX service itself was successfully validated, and it produced a speedup in the smoke sample, but this evaluation does **not** confirm a robust full-workload M3 Max speedup for the rebuilt Rust pipeline. The primary result is a quality regression and end-to-end latency regression versus the supplied pre-parity Rust baseline.

## Validation and cleanup

`PYTHONPATH=src:scripts .venv/bin/python -B scripts/test_research_rust_full_eval.py` completed with `14` tests passed and exit code `0`. The final service checks returned HTTP `200` for ports `8001`, `18081`, and `6333`; port `18083` had no listener after the owned MLX process tree was terminated.
