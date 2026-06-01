# Protogen vLLM Embedding Model Comparison - 2026-06-01

Run artifact: `.code-diver/reports/protogen-vllm-embedding-benchmark.json`

Dataset: `datasets/protogen_eval_100.jsonl`

Index profile: rich deterministic Protogen profile from `configs/protogen-ollama-qdrant.yml` with Qdrant storage override.

Candidate/rerank hypotheses:

- `hybrid_candidates_symbol_first`
- `hybrid_rerank_flash_lite_top20_compact`
- `hybrid_rerank_flash_lite_file_first`

Generation provider for LLM rerank: Gemini API, `gemini-3.1-flash-lite`, `api_version: v1beta`.

Embedding provider under test: local vLLM-Metal OpenAI-compatible `/v1/embeddings`.

## Summary

Best current embedding setup for this profile:

```text
mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ
+ hybrid_rerank_flash_lite_file_first
```

This reaches `Hit@1=0.76`, `Hit@10=0.94`, `MRR@10=0.832`, `nDCG@10=0.763`, and `MAP@10=0.703`.

The larger `Qwen3-Embedding-4B-4bit-DWQ` improves deterministic candidate generation, but it does not improve the best LLM-reranked result. It ties `Hit@1=0.76` and loses on `Hit@10`, `MRR@10`, `nDCG@10`, and `MAP@10` while indexing about 6.7x slower.

## Results

| Embedding model | Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | MAP@10 | Mean search | LLM tokens | LLM cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3 Embedding 0.6B 4-bit | `hybrid_candidates_symbol_first` | 0.52 | 0.72 | 0.86 | 0.634 | 0.607 | 0.535 | 318ms | 0 | $0.000 |
| Qwen3 Embedding 0.6B 4-bit | `hybrid_rerank_flash_lite_top20_compact` | 0.73 | 0.86 | 0.90 | 0.792 | 0.731 | 0.675 | 1,477ms | 475,097 | $0.130 |
| Qwen3 Embedding 0.6B 4-bit | `hybrid_rerank_flash_lite_file_first` | 0.76 | 0.90 | 0.94 | 0.832 | 0.763 | 0.703 | 2,523ms | 1,136,185 | $0.312 |
| Qwen3 Embedding 4B 4-bit | `hybrid_candidates_symbol_first` | 0.56 | 0.76 | 0.90 | 0.673 | 0.633 | 0.546 | 243ms | 0 | $0.000 |
| Qwen3 Embedding 4B 4-bit | `hybrid_rerank_flash_lite_top20_compact` | 0.69 | 0.83 | 0.92 | 0.766 | 0.717 | 0.654 | 1,667ms | 478,612 | $0.131 |
| Qwen3 Embedding 4B 4-bit | `hybrid_rerank_flash_lite_file_first` | 0.76 | 0.88 | 0.92 | 0.820 | 0.752 | 0.692 | 2,691ms | 1,151,926 | $0.317 |

## Index Cost

| Embedding model | Indexed items | Estimated input tokens | Index duration | Total model-server run duration | Local embedding cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3 Embedding 0.6B 4-bit | 12,698 | 1,228,614 | 138.7s | 591.8s | $0 |
| Qwen3 Embedding 4B 4-bit | 12,698 | 1,228,614 | 926.4s | 1,407.8s | $0 |

The total server run duration includes server startup, indexing, all search evaluations, and LLM rerank wait time. The index duration is the cleaner comparison for embedding throughput.

## Compatibility Failures

These models were in the suite but do not currently load through the vLLM-Metal MLX path used by this benchmark:

| Model | Outcome | Root cause from log |
| --- | --- | --- |
| `mlx-community/mxbai-embed-large-v1` | failed before ready | `Model type bert not supported` |
| `mlx-community/bge-m3-mlx-4bit` | failed before ready | `Model type xlm-roberta not supported` |
| `mlx-community/nomicai-modernbert-embed-base-4bit` | failed before ready | `Model type modernbert not supported` |

This does not prove those embedding models are bad. It only proves they are not usable through the current vLLM-Metal/MLX loader path. To test BERT/XLM-RoBERTa/ModernBERT embeddings, use a SentenceTransformers-style local provider or another runtime.

## Ranking Interpretation

`Qwen3-Embedding-4B` is better as a deterministic candidate generator:

- `Hit@1`: 0.52 -> 0.56
- `Hit@10`: 0.86 -> 0.90
- `MRR@10`: 0.634 -> 0.673

But after Gemini Flash Lite file-first rerank, the larger embedder does not win:

- `Hit@1`: tie at 0.76
- `Hit@10`: 0.94 -> 0.92
- `MRR@10`: 0.832 -> 0.820
- `nDCG@10`: 0.763 -> 0.752
- `MAP@10`: 0.703 -> 0.692

So the bottleneck for the best profile is not simply embedding model size. The current quality lever is still candidate formatting plus rerank behavior.

## Harness Findings

The benchmark harness now supports:

- loading `.env` before provider construction;
- benchmark suites that select experiment hypotheses instead of only raw strategy names;
- search-time config overrides, used here to switch rerank to Gemini API `v1beta`;
- per-model vLLM-Metal server startup and teardown;
- progressive JSON report output.

Found issue: query embeddings are recomputed once per hypothesis even though the dataset queries are identical. This inflates evaluation time, especially for slow local embedding models. Add a query embedding cache before running larger IntelliJ-scale suites.

Found operational issue: old generated Qdrant benchmark collections can exhaust Qdrant WAL space. The local run required cleanup of stale generated collections before the successful 4B run.

## Local Quantized Ranker Track

The next model comparison should not put Qwen/Gemma instruct models into the embedding slot. They should be tested as local search/rerank judges over structured candidates.

Plan file: `docs/local-quantized-ranker-plan-2026-06-01.md`

Initial quantized candidates:

- Qwen3-Reranker-4B GGUF Q4/Q5 as the specialized reranker baseline.
- Qwen3.5-4B MLX OptiQ 4-bit or GGUF Q4_K_M as a local search judge.
- Gemma 4 E2B 4-bit as the fast local judge.
- Gemma 4 E4B OptiQ/4-bit as the higher-quality local Gemma judge.

Acceptance criterion: promote a local ranker only if it beats the current Gemini Flash Lite file-first profile on quality, cost, fully-local execution, or IntelliJ-scale stability.
