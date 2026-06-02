# IntelliJ H2 Post-Ranking Benchmark

Date: 2026-06-02

## Goal

Compare two post-locator search scenarios across three orchestrator/ranker models.

The persistent index is intentionally fixed: a compact IntelliJ file-locator index using local Qwen embeddings in Qdrant. This benchmark is about what happens after likely files are found.

## Matrix

| ID | Scenario | Orchestrator / Ranker | Status |
| --- | --- | --- | --- |
| A1 | Locator -> outline/symbol/rg/grep/read -> rerank | Qwen3.5 4B local | Ran 10-case smoke |
| B1 | Locator -> ephemeral syntax-aware local vector search -> rerank | Qwen3.5 4B local | Ran 10-case smoke |
| A2 | Locator -> outline/symbol/rg/grep/read -> rerank | Gemini 3.1 Flash Lite via Vertex | Configured, not run |
| B2 | Locator -> ephemeral syntax-aware local vector search -> rerank | Gemini 3.1 Flash Lite via Vertex | Configured, not run |
| A3 | Locator -> outline/symbol/rg/grep/read -> rerank | Gemini 3.5 Flash via Vertex | Configured, not run |
| B3 | Locator -> ephemeral syntax-aware local vector search -> rerank | Gemini 3.5 Flash via Vertex | Configured, not run |

The Vertex/Gemini runs were not executed in this batch because the approval reviewer rejected the command that would send repository-derived prompts/evidence to an external API. The config is ready, but those four hypotheses need explicit approval in an environment where external model calls are allowed.

## Fixes Made Before The Valid Smoke

Two experiment-validity bugs were found during the first local attempts.

1. The prompt builder mentioned tools that were not available in a hypothesis. Branch B did not have `code_diver_read`, but the prompt still instructed the model about read usage, causing repeated `tool_not_allowed` loops.
2. Branch B only exposed `code_diver_ephemeral_search`; it did not enforce using it. The model could skip the scenario under test and go directly from locator to rerank/final answer.

The current code now:

- builds search prompts from the actual tool manifest;
- tells the model never to call absent tools;
- runtime-forces `code_diver_ephemeral_search` for hypotheses whose name contains `ephemeral`;
- fail-soft returns accumulated candidates with an error flag when the local model breaks JSON/tool protocol.

## Baseline

Same first 10 IntelliJ cases, deterministic file locator only:

| Run | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | File Recall@10 | MRR@10 | NDCG@10 | MAP@10 | Mean ms | P95 ms | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Local Qwen file locator | 0.20 | 0.50 | 0.60 | 0.60 | 0.060 | 0.60 | 0.60 | 0.370 | 0.428 | 0.370 | 80 | 468 | 0 |

This is the key control: the compact local locator already gets the answer into top 5/10 on 60% of this small sample, but rank 1 is weak.

## Main Local Smoke

Raw artifacts:

- `.code-diver/reports/intellij-postrank-h2-qwen-local-rerank-enforced-10.json`
- `.code-diver/reports/intellij-postrank-h2-qwen-local-rerank-enforced-10.html`
- `.code-diver/traces/orchestrator-search/8c4d91256799/`

| Run | Scenario | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | File Recall@10 | MRR@10 | NDCG@10 | MAP@10 | Mean ms | P95 ms | Errors | Model Calls | Tool Calls | Tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | grep/read/rerank | 0.40 | 0.50 | 0.60 | 0.60 | 0.125 | 0.60 | 0.60 | 0.470 | 0.502 | 0.470 | 23,001 | 46,528 | 7 | 29 | 17 | 104,577 |
| B1 | ephemeral/rerank | 0.40 | 0.50 | 0.60 | 0.60 | 0.125 | 0.60 | 0.60 | 0.470 | 0.502 | 0.470 | 15,011 | 28,056 | 9 | 26 | 16 | 83,366 |

95% CI on Hit@1 for both local runs: `0.168 .. 0.687`, width `0.519`. With only 10 cases, the confidence interval is huge; these numbers are useful as smoke diagnostics, not final quality claims.

## Tool Usage

| Run | Completed | Completed With Error | Actual Tool Calls | Fallbacks |
| --- | ---: | ---: | --- | --- |
| A1 | 10 | 7 | `search=10`, `rerank=4`, `outline=2`, `read=1` | `agent_protocol_error_last_candidates=7` |
| B1 | 10 | 9 | `search=12`, `ephemeral=3`, `rerank=1` | `agent_protocol_error_last_candidates=6`, `exception_last_candidates=3`, `max_rounds_last_candidates=1` |

Branch B only reached actual `code_diver_ephemeral_search` in 3 of 10 cases. The runtime enforcement works when the model returns parseable tool protocol, but local Qwen often returns invalid or incomplete JSON before the forced step can run.

## Readout

The local Qwen orchestrator did improve rank-1 on this sample versus the deterministic locator (`0.20 -> 0.40`), while preserving Hit@5/10. That means LLM ranking can help when the correct file is already in the locator candidate set.

The local Qwen orchestrator is not reliable enough for a 100-case agentic sweep yet. Error rates of 70-90% mean a larger run would mostly measure prompt/protocol brittleness, not the search strategy.

Branch B did not yet prove that localized ephemeral indexing improves quality. In the enforced smoke it matched Branch A on quality and was faster, but it only truly used ephemeral search in 3/10 cases. We need a deterministic scenario runner that executes the required tool sequence and uses the model only for ranking, or constrained JSON/tool calling for the local model.

## Next Step

For a fair 6-way comparison, the next runner should execute the scenario skeleton deterministically:

- A: locator top N -> selected outline/symbol/rg/read probes -> model rerank.
- B: locator top N -> forced ephemeral syntax-aware index/search -> model rerank.

Then the only model-variable part is ranking/orchestration choice, not whether the model remembered to call the required scenario tool. After that, run A/B for Qwen local, Gemini Flash Lite, and Gemini Flash on 100 cases, then promote the winner to 1000.
