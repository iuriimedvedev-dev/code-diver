# Local Model Axis Experiments

Date: 2026-06-04

## Experiment Rule

Code Diver has three independent model axes:

1. Embedding model: controls H3/H5 candidate recall and initial ordering.
2. Reranker model: controls ordering of a bounded candidate list.
3. Agent model: controls query planning, tool use, verification, and answer synthesis.

Experiments must change one axis at a time. If two or three axes change together, the result is not causal enough to choose a default.

## H6.1 / H6.2 Calibration Status

H6.1 calibrated fixed hybrid weights on the 700/300 CodeSearchNet split. It improved head ranking slightly, but did not improve candidate coverage:

| Profile | file Hit@1 | file Hit@5 | file Hit@10 | file MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| Manual H5 weights | 0.837 | 0.947 | 0.960 | 0.888 |
| Best calibrated weights | 0.843 | 0.953 | 0.960 | 0.893 |

H6.2 now has two MLP modes:

| Mode | Meaning | 80/20 smoke result |
| --- | --- | --- |
| `scalar` | Predict one score per candidate. | Worse than fixed weights: file Hit@10 `0.550`. |
| `weights` | Predict a dynamic vector over hybrid signals, then score by weighted sum. | Preserved file Hit@10 `0.850`, but worsened file Hit@3/5 and MRR. |

Decision: keep H6.1 as an active calibration candidate. Keep H6.2 as research only until a better listwise/pairwise loss beats H6.1 on held-out data.

## Embedding Axis: 100-Case Smoke

Suite:

```bash
uv run --group runtime-sentence-transformers python scripts/benchmark_embedding_models.py \
  --suite configs/codesearchnet-local-embedding-axis-100.yml
```

Report:

```text
.code-diver/reports/codesearchnet-local-embedding-axis-100.json
```

Fixed variables:

| Axis | Value |
| --- | --- |
| Search/index shape | H5 file metadata: `file_summary` + `file_manifest`, no code-body vectors |
| Search strategy | deterministic `hybrid`, no LLM reranker |
| Dataset | `.code-diver/tmp/codesearchnet_python_100.jsonl` |
| Hybrid weights | H5 manual weights |

Changed variable: embedding model.

| Embedding model | Provider | Index seconds | file Hit@1 | file Hit@3 | file Hit@5 | file Hit@10 | file MRR@10 | nDCG@10 | mean search ms | semantic file Hit@1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` | `openai_compatible` | 44.2 | 0.750 | 0.930 | 0.940 | 0.950 | 0.843 | 0.870 | 557.9 | 0.500 |
| `google/embeddinggemma-300m` | `sentence_transformers` | 56.5 | 0.810 | 0.930 | 0.940 | 0.950 | 0.873 | 0.892 | 853.0 | 0.643 |

Interpretation:

- EmbeddingGemma is a real candidate. It improved head ranking and semantic-query head accuracy on this split.
- Hit@10 tied at `0.950`, so this smoke does not prove better candidate coverage.
- The confidence intervals are wide on 100 cases. This is a promotion signal to 1,000 cases, not a final winner.
- The current `sentence_transformers` provider is in-process and slower for query encoding than the already-hot Qwen embedding server. If EmbeddingGemma wins quality on 1,000 cases, the next runtime task is to keep it hot behind a server or persistent worker.

## Next Matrix

Embedding axis:

| Candidate | Status |
| --- | --- |
| Qwen3-Embedding-0.6B 4-bit | baseline, integrated |
| EmbeddingGemma-300M | integrated through `sentence_transformers`, promote to 1,000-case run |
| Qwen3-Embedding-4B | pending runtime/download validation |

Reranker axis:

| Candidate | Status |
| --- | --- |
| Gemini 3.1 Flash Lite | API quality/cost baseline |
| Qwen3-Reranker-0.6B cross-encoder | local endpoint exists, needs same H3 candidate suite |
| Qwen3-Reranker-4B cross-encoder | pending model/runtime |
| Qwen3.5 4B listwise | local fallback, slower in prior runs |
| Gemma E2B/E4B listwise | configs exist, needs same 100-case reranker-axis run |

Agent axis:

| Candidate | Status |
| --- | --- |
| Gemini 3.1 Flash Lite | API control |
| Qwen3.5 4B | local agent candidate |
| Gemma E2B/E4B | local agent candidate |

The next valid experiments should hold the embedding axis fixed and compare rerankers, then hold embedding+reranker fixed and compare agent models.

## Reranker Axis: Gemma E4B 100-Case Smoke

Suite:

```bash
uv run python scripts/benchmark_generation_models.py \
  --suite configs/codesearchnet-local-gemma-ranker-slice.yml \
  --only gemma4_e4b_it_optiq_4bit
```

Report:

```text
.code-diver/reports/codesearchnet-local-gemma-ranker-slice.json
```

Fixed variables:

| Axis | Value |
| --- | --- |
| Embedding model | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` |
| Candidate generator | H5/H3 Qwen file-metadata index |
| Dataset | `.code-diver/tmp/codesearchnet_python_100.jsonl` |
| Rerank input | top-30 candidates, top-10 output, compact previews |

Changed variable: reranker model.

| Reranker | Runtime | file Hit@1 | file Hit@3 | file Hit@5 | file Hit@10 | file MRR@10 | mean search ms | p95 ms | calls | tokens | est. cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pure H3, no rerank | Qwen embedding server only | 0.750 | 0.930 | 0.940 | 0.950 | 0.843 | 557.9 | 583.5 | 0 | 0 | 0 |
| Gemma 4 E4B OptiQ 4-bit listwise | `mlx_lm` | 0.560 | 0.590 | 0.590 | 0.590 | 0.573 | 8049.1 | 9332.2 | 100 | 1,050,072 | 1.616 |

Interpretation:

- This local generative Gemma E4B reranker is a clear rejection in the current H5 protocol.
- It degraded candidate coverage and ordering instead of improving them.
- It is about `14.4x` slower than Pure H3 on the same 100-case split.
- The most likely failure mode is not model startup: the server ran and returned 100 successful calls. The problem is ranking behavior/protocol fit.
- Next reranker work should prioritize dedicated cross-encoders such as Qwen3-Reranker over local generative listwise ranking.
