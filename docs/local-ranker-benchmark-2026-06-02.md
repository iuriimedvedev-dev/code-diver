# Local Ranker Benchmark - 2026-06-02

## Scope

This benchmark compares local generation models as LLM rerankers on top of the same retrieval setup:

- Dataset: `datasets/protogen_eval_30.jsonl`
- Indexed repo: sibling `protogen`
- Index: existing Qdrant collection `protogen_vllm_embeddings_vllm_qwen3_embedding_0_6b_mlx_4bit_4a455c9c66f7`
- Embedding model: `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` served through vLLM pooling
- Retrieval baseline: `hybrid_candidates_symbol_first`
- Rerank strategy: `hybrid_rerank_flash_lite_top20_compact`

The goal was to compare local reranker quality, speed, startup cost, and runtime reliability. The benchmark intentionally keeps the embedding/index fixed so ranker changes are isolated.

## Result Table

| Model | Precision | Quantization | Startup s | Hit@1 | Hit@10 | MRR@10 | nDCG@10 | MAP@10 | Mean ms/query | LLM calls | Errors | Tokens | Est. cost |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen35_4b_mlx_4bit` | 4bit | uniform-4bit | 6.3 | 0.533 | 0.933 | 0.665 | 0.688 | 0.611 | 6158.3 | 28 | 2 | 121458 | 0.2218 |
| `qwen35_4b_mlx_bf16` | bf16 | none | 755.3 | 0.567 | 0.933 | 0.681 | 0.702 | 0.625 | 9201.4 | 30 | 0 | 130158 | 0.2362 |
| `qwen35_4b_optiq_4bit` original | 4bit | optiq-4bit | 322.4 | 0.500 | 0.867 | 0.605 | 0.632 | 0.564 | 7440.0 | 0 | 30 | 0 | 0.0000 |
| `gemma4_e2b_it_4bit` | 4bit | uniform-4bit | 307.4 | 0.567 | 0.900 | 0.688 | 0.678 | 0.613 | 2124.5 | 30 | 0 | 139021 | 0.2316 |
| `gemma4_e2b_it_bf16` | bf16 | none | 839.1 | 0.633 | 0.900 | 0.716 | 0.698 | 0.632 | 3465.5 | 30 | 0 | 139448 | 0.2354 |
| `gemma4_e4b_it_4bit` | 4bit | uniform-4bit | 460.4 | 0.567 | 0.900 | 0.663 | 0.674 | 0.612 | 4430.6 | 30 | 0 | 139108 | 0.2324 |
| `qwen35_4b_optiq_4bit` fixed | 4bit | optiq-4bit | 4.7 | 0.567 | 0.933 | 0.691 | 0.710 | 0.635 | 6567.9 | 30 | 0 | 130438 | 0.2388 |
| `gemma4_e4b_it_optiq_4bit` | 4bit | optiq-4bit | 609.8 | 0.500 | 0.867 | 0.605 | 0.632 | 0.564 | 7530.4 | 0 | 30 | 0 | 0.0000 |

The deterministic baseline row is the same candidate generator used before rerank: Hit@1 `0.500`, Hit@10 `0.867`, MRR@10 `0.622`, nDCG@10 `0.626`, mean latency about `0.72-1.01s/query` depending on warmed embedding cache.

## Findings

1. The original Qwen OptiQ run was invalid. It had `0` successful LLM calls and `30` errors, so it measured a runtime/protocol failure, not model quality.
2. Qwen OptiQ fixed is currently the best quality local reranker by nDCG@10: `0.710`. The fix was to launch `mlx_lm.server` with `chat_template_args: {"enable_thinking": false}` and to allow the OpenAI-compatible provider to read `reasoning_content`/`reasoning` when `content` is empty.
3. Gemma E2B bf16 has the best Hit@1: `0.633`, with strong MRR@10 `0.716`, but its cold start was `839s`. It is only a practical candidate as a warmed persistent service.
4. Gemma E2B 4bit is the best speed/quality local option: `0.567` Hit@1, `0.688` MRR@10, `0.678` nDCG@10, and `2124ms/query`. It is the current interactive local default candidate.
5. Gemma E4B 4bit did not beat Gemma E2B 4bit. It was slower and slightly worse on nDCG.
6. Gemma E4B bf16 is impractical in the current quick harness. Cold startup exceeded the configured `1200s` readiness window and exposed a cleanup bug in the benchmark runner.
7. Gemma E4B OptiQ is not valid with the current strict JSON reranker contract. The server responded, but all 30 rerank attempts failed with `ValueError: JSON response does not contain an object.`

## Runtime Fixes Made

- Added `chat_template_args` support to `scripts/benchmark_generation_models.py` for `mlx_lm.server`.
- Configured Qwen OptiQ with `{"enable_thinking": false}` in local benchmark configs.
- Extended `OpenAICompatibleGenerationProvider` to extract text from OpenAI-style content lists, `reasoning_content`, `reasoning`, and legacy top-level `text`.
- Added SIGKILL fallback to benchmark server cleanup so one stuck local model does not crash the entire matrix.
- Added tests for response-format fallback, query embedding caching, and reasoning-content extraction.

## Top 3 Candidates

1. `qwen35_4b_optiq_4bit` fixed: best nDCG/MAP, reasonable startup after cache, but slower per query.
2. `gemma4_e2b_it_bf16`: best Hit@1 and MRR, but only acceptable when preloaded as a persistent service.
3. `gemma4_e2b_it_4bit`: best practical interactive local reranker today; fastest valid model with meaningful quality lift.

## Next Hypotheses

- Add JSON repair / constrained decoding for models that return rank text instead of a strict JSON object.
- Benchmark `optiq serve` directly for OptiQ models instead of plain `mlx_lm.server`, especially for Gemma OptiQ.
- Split cold-start metrics from warm-service metrics in the harness.
- Run the top 3 on the full `datasets/protogen_eval_100.jsonl`.
- Re-run the same ranker matrix with Gemini embeddings when Vertex ADC is refreshed.
