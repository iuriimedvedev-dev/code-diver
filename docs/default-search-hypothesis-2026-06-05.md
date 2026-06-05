# Default Search Hypothesis - 2026-06-05

## Decision

Use **H6.1 EmbeddingGemma static hybrid** as the default search/index profile.

This is the best validated local default we have right now: no API dependency during
retrieval, compact file-level index, strong Hit@3/Hit@5/Hit@10, and stable enough to
make the public CLI reproducible.

## Default Stack

| Layer | Default |
| --- | --- |
| Persistent index | File summaries + file manifests only |
| Durable code-body vectors | No |
| Embedding model | `google/embeddinggemma-300m` |
| Embedding dimensions | 768 |
| Search strategy | `hybrid` |
| Ranker | None by default; LLM/agent rerank is an experiment |
| Public benchmark profile | `codesearchnet-mteb-python-1000` |
| Benchmark config | `configs/codesearchnet-mteb-python-h5-embeddinggemma-quality.yml` |

The current calibrated weights:

| Signal | Weight |
| --- | ---: |
| vector | 0.5625 |
| lexical | 0.1875 |
| path | 0.08333333333333334 |
| symbol | 0.04166666666666667 |
| symbol_match | 0.04166666666666667 |
| graph | 0.08333333333333334 |
| file_vote | 0.0 |

## Evidence

CodeSearchNet/MTEB Python local positive slice:

| Run | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H6.1 EmbeddingGemma static smoke | 100 | 0.810 | 0.920 | 0.960 | 0.970 | 0.970 | n/a | 0.876 | 0.899 | n/a |
| H6.1 EmbeddingGemma calibrated validation | 300 | 0.863 | 0.953 | 0.973 | 0.983 | 0.983 | n/a | 0.911 | n/a | n/a |
| H6.1 EmbeddingGemma 1000 slice | 1000 | 0.848 | 0.947 | 0.964 | 0.975 | 0.975 | 0.173 | n/a | 0.918 | 787 |
| Qwen3-Embedding-0.6B calibrated validation | 200 | 0.755 | 0.900 | 0.925 | 0.950 | 0.950 | n/a | 0.833 | n/a | n/a |

The 300-case validation row is the strongest held-out evidence for the calibrated
weights. The 1000-case row is the broader public-slice operating point.

## Why This Beats The Previous Default

The previous practical default was Qwen3-Embedding-0.6B with manual H3/H5 weights,
and optional Gemini Lite reranking. It remains useful as a fast control, but the
EmbeddingGemma candidate generator improved the local no-rerank ceiling enough to
be the safer default:

- Qwen0.6B calibrated validation: Hit@10 `0.950`, MRR `0.833`.
- EmbeddingGemma calibrated validation: Hit@10 `0.983`, MRR `0.911`.

H6.2 MLP weighting did not clear the requested `+0.05` improvement threshold. It is
kept as research, not promoted.

## Why Agent/LLM Rerank Is Not The Default Yet

LLM ranking is still the likely quality layer, but current local agent/rerank runs
do not have a valid 1000-case result over the same H6.1 index. Existing small gates
are useful but not enough to promote:

| Agent/ranker | Cases | Hit@10 | Mean ms | Status |
| --- | ---: | ---: | ---: | --- |
| Gemini 3.1 Flash Lite agent axis | 25 | 0.920 | 11,320 | valid, small |
| Qwen3.5 4B agent axis | 10 | 1.000 | 37,020 | promising, too small/slow |
| Gemma 4 E4B agent axis | 10 | 0.900 | 56,573 | too slow |
| Gemma 4 E2B 1000 attempt | n/a | n/a | n/a | invalid zero-byte artifact |

Promotion rule: a reranker/agent becomes default only after a same-index, non-degraded
run beats H6.1 by at least `+0.02 Hit@1` without reducing Hit@10 and with an acceptable
latency/cost profile.

## Implementation Status

- `Defaults` now point to EmbeddingGemma-300M and the calibrated H6.1 weights.
- `init --yes` chooses `embeddinggemma-300m` on Apple Silicon and
  `embeddinggemma-300m-vllm` on CUDA/ROCm/CPU.
- `evaluate --benchmark codesearchnet-mteb-python-1000` points to the EmbeddingGemma
  H6.1 quality config and uses the same OpenAI-compatible embedding endpoint configured
  by `init`.
- `hash` remains only the explicit no-key smoke benchmark.

## Verification Notes

- `uv run pytest -q` passed: 338 tests.
- Before the benchmark config was aligned to the OpenAI-compatible runtime endpoint, a
  live 5-case JSON smoke used the older in-process `sentence_transformers` path and was
  stopped after more than a minute with no JSON output. The config is now aligned to the
  `init --start` runtime path; endpoint-live benchmark smoke still needs a running
  embedding server.
