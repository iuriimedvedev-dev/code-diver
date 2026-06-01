# Local Quantized Ranker Plan - 2026-06-01

Goal: test whether a small local model can close the remaining ranking gap after the rich deterministic index finds a good candidate pool.

This is a search/rerank experiment, not an embedding experiment. The embedding benchmark keeps using the best local embedding candidates through vLLM/Qdrant. These models sit after retrieval and judge candidate files/items.

## Why This Layer Exists

Current Protogen numbers show candidate generation is already strong: the expected target is usually in the candidate pool, but the top result is still often the wrong neighboring file, symbol, or chunk. That is exactly where a local ranker should help:

1. Read the natural-language query.
2. Inspect structured candidates from vector, BM25, symbols, graph, and grep.
3. Optionally request a tiny focused code snippet for the top ambiguous files.
4. Return a ranked list with file paths, line numbers, confidence, and short evidence.

The local model is only allowed to rank and inspect. Indexing remains deterministic for this track.

## Runtime Constraint

Use quantized local models only.

Preferred formats:

- MLX 4-bit or mixed 4/8-bit OptiQ for Apple Silicon generation.
- GGUF Q4_K_M, Q5_K_M, or Q6_K for llama.cpp-compatible generation/rerank serving.
- No full BF16/FP16 checkpoints unless a quantized candidate fails and we need a one-off diagnostic.

## Candidate Matrix

| Role | Candidate | Quant format | Why test it |
| --- | --- | --- | --- |
| Reranker baseline | `batiai/Qwen3-Reranker-4B-GGUF` or another Qwen3-Reranker-4B GGUF Q4/Q5 build | GGUF Q4_K_M or Q5_K_M | Specialized pairwise/listwise relevance model; should beat generic instruct models on candidate ordering. |
| Search judge | `mlx-community/Qwen3.5-4B-OptiQ-4bit` | MLX mixed 4/8-bit | Strong small tool/instruction model for Apple Silicon; useful for query planning and final ranking explanations. |
| Search judge fallback | `Qwen/Qwen3-4B-GGUF` or `Qwen3-4B-Instruct-2507` quant | GGUF/MLX 4-bit | Public stable 4B Qwen fallback if Qwen3.5 checkpoints are unstable in the local server path. |
| Fast Gemma judge | `mlx-community/gemma-4-e2b-it-4bit` or a PLE-safe Gemma E2B 4-bit build | MLX/GGUF 4-bit | Very small local judge; target is low latency, not maximum accuracy. |
| Higher-quality Gemma judge | `mlx-community/gemma-4-e4b-it-OptiQ-4bit`, `mlx-community/gemma-4-e4b-it-4bit`, or GGUF Q4_K_M | MLX/GGUF 4-bit | Larger Gemma Edge model; useful to compare against Qwen for tool-following and ranking. |

Qwen 3.7 is not added as a hard dependency until we verify a stable public quantized checkpoint. If a reliable 4B-ish Qwen 3.7 quant appears, add it as another search judge row, not as a replacement for the reranker baseline.

## Experiment Design

Use the same fixed candidate pool for every local ranker:

- Dataset: `datasets/protogen_eval_100.jsonl` first, then IntelliJ 1k.
- Index profile: best rich deterministic profile available at the time of the run.
- Candidate sources: vector, BM25/lexical, symbols, structural chunks, graph expansion, and grep fallback.
- Candidate count: evaluate top 20 and top 40.
- Snippet budget: evaluate no-snippet, 3-file focused snippets, and 5-file focused snippets.
- Output contract: JSON with ranked file paths, line numbers, confidence, evidence ids, and refusal/error metadata.

Run these hypotheses:

| Hypothesis | Description |
| --- | --- |
| `local_reranker_qwen3_4b_q4_top20` | Specialized Qwen3 reranker scores top-20 candidates. |
| `local_reranker_qwen3_4b_q4_top40` | Same model over top-40 to test recall-vs-latency. |
| `local_search_qwen35_4b_optiq_top20_snippets3` | Qwen3.5 4B ranks top-20 with up to 3 focused snippets. |
| `local_search_gemma4_e2b_q4_top20_snippets3` | Fast Gemma E2B judge over top-20 with snippets. |
| `local_search_gemma4_e4b_optiq_top20_snippets3` | Higher-quality Gemma E4B judge over top-20 with snippets. |
| `cascade_reranker_then_judge` | Specialized reranker reduces top-40 to top-8, then search judge resolves ambiguous files. |

## Metrics

Primary quality:

- Hit@1, Hit@3, Hit@10
- MRR@10
- nDCG@10
- MAP@10
- file-level MRR@10

Cost/performance:

- wall-clock latency mean, p50, p95
- model load time
- prompt tokens, completion tokens, total tokens
- local estimated tokens/sec
- memory footprint if measurable
- snippet reads per query
- candidate count consumed per query

Reliability:

- invalid JSON rate
- empty ranking rate
- path-not-in-candidates rate
- timeout rate
- deterministic rerun agreement
- error category distribution

Tool behavior:

- which candidate source produced the final answer
- how often snippets changed the winner
- how often grep-only candidates won
- how often graph neighbors won
- how often the local judge overrode a correct deterministic top-1

## Acceptance Criteria

Promote a local ranker only if it beats the current Gemini Flash Lite file-first rerank tradeoff on at least one clear axis:

- higher Hit@1 at comparable latency,
- same Hit@1 with much lower cost,
- same quality with fully local execution,
- or better IntelliJ-scale stability.

Reject a model if it improves average metrics by demoting too many already-correct deterministic top-1 results. The report must include win/loss movement against the deterministic baseline and against Gemini Flash Lite rerank.

## Implementation Notes

The ranker should be a provider-agnostic tool behind the same search orchestration contract:

- input: query, structured candidates, optional snippets, ranking instructions;
- output: structured ranked candidates with confidence and evidence;
- no write/edit tools;
- no direct filesystem path reads except through existing guarded read tools;
- strict timeout and structured error capture;
- full trace of prompts, tool calls, candidate ids, and final ranking.

For local serving, prefer an OpenAI-compatible endpoint so the same provider interface can talk to vLLM, llama.cpp server, or MLX server.
