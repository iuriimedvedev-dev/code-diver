# MLX versus llama.cpp benchmark — 2026-09-08

## Decision

Ran the requested direct MLX warm rerank benchmark against the live llama.cpp
`http://127.0.0.1:18081/v1/rerank` endpoint. This is runtime evidence only:
`mlx-community/Qwen3-Reranker-0.6B-4bit` is an MLX 4-bit conversion, while the
baseline is `Qwen3-Reranker-0.6B-Q4_K_M.gguf`; the quantization artifacts differ,
so the result is not quality acceptance.

## Method

- Input: `artifacts/research/2026-09-08_metal-runtime/payloads_v2.json`.
- Both caps used the same 34 documents and query.
- MLX used the official Qwen3 model-card prompt and final-position
  `softmax([logit(no), logit(yes)])[1]` scoring.
- Verified token IDs: `yes=9693`, `no=2152`.
- MLX model load was outside timing; each document ran sequentially with
  `batch_size=1`, `mx.eval`, and `mx.synchronize`.
- Two warmups and three timed repetitions per backend/cap; randomized paired
  condition order with seed `42`; no concurrent GPU calls.
- The smoke and full runs had zero errors; every timed condition produced 34/34
  finite probabilities.

## Results

| Cap | MLX timed seconds | HTTP timed seconds | MLX mean / HTTP mean |
|---:|---|---|---:|
| 850 | 42.617924, 23.001591, 2.661825 | 2.007128, 6.265126, 2.037769 | 22.760447 / 3.436674 |
| 2400 | 101.046208, 91.134174, 11.559149 | 5.363247, 4.468724, 4.419027 | 67.913177 / 4.750333 |

MLX timed runtime was slower and highly variable in this sequential workload.
Top-10 overlap was `9/10` at both caps, but common-item order differed. Absolute
score deltas at or above `0.3` occurred at indices `5,13` for cap `850`, and
`5,10,13,23` for cap `2400`; threshold flips occurred at `5,13` and `5,10,13`,
respectively.

## Artifacts

- Raw evidence: `artifacts/research/2026-09-08_mlx-benchmark/benchmark_raw.json`
- Derived checks: `artifacts/research/2026-09-08_mlx-benchmark/summary.json`
- Smoke evidence: `artifacts/research/2026-09-08_mlx-benchmark/smoke.json`
- Full research report: `docs/research/2026-09-08_mlx-benchmark.md`

No application code, project config, installation, service restart, or `HOME`
environment change was performed.