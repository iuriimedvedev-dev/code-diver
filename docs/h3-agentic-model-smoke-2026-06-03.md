# H3 Agentic Model Smoke - 2026-06-03

This report records a 10-case smoke test of the H3 Agentic search loop on the IntelliJ answer-set dataset.

The goal was not to produce final product metrics. The goal was to verify that the agentic entrypoint works with the three requested orchestrator/ranker candidates and to identify which runs are worth scaling to 100/1000 cases.

## Setup

Dataset slice:

```text
.code-diver/tmp/intellij_eval_10.answer_sets.jsonl
```

Base config:

```text
configs/intellij/intellij-postrank-h3-manifest.yml
```

The tested hypotheses were:

| Hypothesis | Model | Provider/runtime | Notes |
| --- | --- | --- | --- |
| `ai_h3_agentic_gemini_flash_lite` | `gemini-3.1-flash-lite` | Vertex AI and standalone Gemini API | Vertex failed before ADC reauth, then passed after `gcloud` relogin. |
| `ai_h3_agentic_qwen35_4b` | `mlx-community/Qwen3.5-4B-OptiQ-4bit` | MLX local OpenAI-compatible server | Valid smoke, but the server was still capped at `--max-tokens 384` while config asks for 1536. |
| `ai_h3_agentic_gemma4_e4b_optiq` | `mlx-community/gemma-4-e4b-it-OptiQ-4bit` | MLX local OpenAI-compatible server | Valid smoke with `enable_thinking=false`. |

## Artifacts

| Run | JSON artifact | Trace |
| --- | --- | --- |
| Gemini Lite API | `.code-diver/reports/h3-agentic-2026-06-03/gemini-lite-api-10.json` | `.code-diver/traces/orchestrator-search/2fd466e11e52/ai_h3_agentic_gemini_flash_lite.jsonl` |
| Gemini Lite Vertex after reauth | `.code-diver/reports/h3-agentic-2026-06-03/gemini-lite-vertex-10.json` | `.code-diver/traces/orchestrator-search/03c55dd2ad9c/ai_h3_agentic_gemini_flash_lite.jsonl` |
| Qwen3.5 4B local | `.code-diver/reports/h3-agentic-2026-06-03/qwen35-4b-10.json` | `.code-diver/traces/orchestrator-search/60dcb9659c5e/ai_h3_agentic_qwen35_4b.jsonl` |
| Gemma 4 E4B local | `.code-diver/reports/h3-agentic-2026-06-03/gemma4-e4b-optiq-10.json` | `.code-diver/traces/orchestrator-search/4917c65425f1/ai_h3_agentic_gemma4_e4b_optiq.jsonl` |

## Metrics

| Setup | Valid | Cases | Errors | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | nDCG@10 | MAP@10 | Mean ms | P95 ms | Model calls | Tool calls | Tokens | Cost field |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini Lite API | Yes | 10 | 0 | 0.60 | 0.80 | 0.80 | 0.90 | 0.750 | 0.309 | 0.658 | 0.588 | 12,411 | 21,180 | 57 | 44 | 316,311 | $0.087 |
| Gemini Lite Vertex after reauth | Yes | 10 | 0 | 0.70 | 0.80 | 0.80 | 0.80 | 0.700 | 0.487 | 0.685 | 0.650 | 11,725 | 16,426 | 56 | 48 | 290,977 | $0.082 |
| Qwen3.5 4B local | Yes | 10 | 0 | 0.60 | 0.70 | 0.70 | 0.90 | 0.750 | 0.200 | 0.695 | 0.659 | 47,613 | 64,287 | 58 | 59 | 341,455 | local estimate $0.607 |
| Gemma 4 E4B local | Yes | 10 | 0 | 0.50 | 0.70 | 0.70 | 0.70 | 0.625 | 0.342 | 0.552 | 0.508 | 40,605 | 50,106 | 59 | 54 | 355,526 | local estimate $0.633 |

The local `Cost field` is the configured token-cost estimator, not actual spend.
The failed pre-reauth Vertex attempt is intentionally excluded from this table because it measured ADC state, not search quality.

## Findings

Gemini 3.1 Flash Lite is the best candidate among these three for the current H3 Agentic loop. It is faster than local Qwen/Gemma by roughly 3.5-4x on this smoke slice and has better or comparable quality. Vertex is now usable again after ADC reauth.

Qwen3.5 4B local is the stronger local candidate. It matched Gemini API on Hit@10 and had the best nDCG/MAP among the local models, but latency is too high for the current open-ended agent loop. It should be tested further only after the MLX server is restarted with the intended max-token budget and after stronger stopping rules are added.

Gemma 4 E4B local is valid but weaker here. It produced lower Hit@1, Hit@10, nDCG, and MAP than Qwen3.5 4B while still being very slow. The trace also showed an `agent_response_retry`, which means the output contract is less stable than needed for large runs.

The failed pre-reauth Vertex attempt confirms a harness bug: infrastructure failures can become search misses if the runner does not fail fast. Such runs must be marked invalid and excluded from quality tables.

## Agentic Loop Behavior

The models did use the intended tool flow:

- `code_diver_h3_search` for candidate generation;
- `code_diver_rerank` for ordering;
- `code_diver_outline`, `code_diver_symbols`, `code_diver_rg`, and `code_diver_read` for verification;
- parallel tool calls in at least some local-model cases.

The problem is over-searching. Local models often continue with extra H3 searches, outlines, reads, or forced reranks after the candidate set is already strong. The runtime also forces rerank after candidate-producing passes for rerank/agentic hypotheses; that helps quality discipline, but it can override a model's intent to verify a tiny code range first.

## Decision

Do not promote H3 Agentic as the default search path yet.

Current ranking for follow-up:

| Rank | Setup | Decision |
| ---: | --- | --- |
| 1 | Gemini 3.1 Flash Lite H3 Agentic | Keep for cheap API agentic experiments and gated hard-case search. |
| 2 | Qwen3.5 4B local H3 Agentic | Keep as local candidate, but only after token/server config is fixed and stop rules are tightened. |
| 3 | Gemma 4 E4B local H3 Agentic | Do not scale until Qwen has been exhausted or Gemma prompt/output stability improves. |

Pure H3 remains the production baseline. H3 Agentic is still a research/hard-case layer until it beats Pure H3 on a valid 100-case run without a large latency/cost penalty.

## Required Fixes Before Scaling

1. Fail fast on provider/auth errors instead of counting them as misses.
2. Add a confidence-gated stop condition after H3 search plus rerank.
3. Separate "agent planner" from "reranker" in metrics so we can see which role each model is failing.
4. Restart local generation servers with the same max-token budget as the config before comparative runs.
5. Prefer a 100-case validation before any new 1000-case local-agentic run.
