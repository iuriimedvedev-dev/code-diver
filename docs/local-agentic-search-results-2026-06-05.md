# Local Agentic Search Results - 2026-06-05

## Question

Can Code Diver run the search intelligence layer fully locally, and how does that
compare with the main baseline: H6.1 local locator plus Gemini 3.1 Flash Lite?

This report is **not** claiming that the product should stop at the locator. The
product pipeline is:

```text
user question
-> H6.1 locator produces ranked candidate files
-> reranker selects/reshuffles the candidate file set
-> orchestrator/explainer reads outlines, symbols, rg/grep hits, and source ranges
-> final answer explains the code with evidence
```

The word `static` in older notes means only: "the locator/ranker is deterministic
and does not call an LLM." It does **not** mean "there is no LLM code-reading
answer step."

Fixed candidate generator:

```text
EmbeddingGemma-300M file summaries + file manifests
-> H6.1 calibrated hybrid locator
-> optional agent/rerank layer
```

Dataset: `.code-diver/tmp/codesearchnet_python_100.jsonl`.

## Results

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Model calls | Tool calls | Tokens | Est. cost | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H6.1 static local locator | 100 | 0.820 | 0.930 | 0.970 | 0.970 | 0.970 | 0.147 | 0.876 | 0.900 | 858 | 863 | 0 | 0 | 0 | 0 | 0 |
| H6.1 + Gemma 4 E2B local agent/rerank | 100 | 0.510 | 0.570 | 0.640 | 0.700 | 0.700 | 0.070 | 0.564 | 0.596 | 11,501 | 12,879 | 406 | 312 | 3,045,868 | local | 0 |
| H6.1 + Gemini 3.1 Flash Lite agent/rerank | 100 | 0.740 | 0.860 | 0.860 | 0.860 | 0.860 | 0.277 | 0.797 | 0.813 | 10,660 | 14,375 | 454 | 330 | 2,509,105 | $0.70 | 0 |

Artifacts:

| Setup | Output | Trace |
| --- | --- | --- |
| H6.1 static | `.code-diver/reports/local-agent-axis/h6-static-100.json` | n/a |
| Gemma E2B local agent | `.code-diver/reports/local-agent-axis/local-agent-e2b-100.json` | `.code-diver/traces/orchestrator-search/9b55d64f7f81/agent_gemma4_e2b_local_rerank.jsonl` |
| Gemini Lite agent | `.code-diver/reports/local-agent-axis/gemini-lite-agent-rerank-100.json` | `.code-diver/traces/orchestrator-search/648799f7565e/agent_gemini_lite_rerank_gemini_lite.jsonl` |

## Interpretation

The fully local Gemma E2B path works technically: zero degraded cases, stable tool
use, and successful early-stop after rerank. It does not work as a combined
orchestrator+reranker for the candidate-file stage yet. It loses `0.33 Hit@5`
and `0.304 nDCG@10` versus the deterministic H6.1 locator, while being roughly
`13x` slower.

Gemini 3.1 Flash Lite is a much stronger intelligence layer than Gemma E2B. It
raises Precision@10 from `0.147` to `0.277`, which means it returns a narrower,
more curated list. But that precision comes at the wrong cost for broad search:
Hit@10 drops from `0.970` to `0.860`.

The current policy is therefore:

1. Keep **H6.1 deterministic locator** as the default broad candidate generator.
2. Use **Gemini 3.1 Flash Lite** as a gated precision/rerank/explanation layer,
   not as an unrestricted agent loop for every query.
3. Keep **Gemma E2B** as a local runtime candidate for explanation or offline
   hard-tail rerank experiments, not default interactive search.

## What This Does And Does Not Answer

This run answers one axis:

| Axis | Answer from this run |
| --- | --- |
| Can Gemma E2B locally run the whole agent+rerank loop? | Yes, technically stable. |
| Is Gemma E2B good enough to rerank candidate files? | No, it demotes too many correct files. |
| Is Gemini Lite better at agent+rerank? | Yes, but still too recall-destructive as an always-on loop. |

It does **not** finish the broader model search:

| Axis | Still needed |
| --- | --- |
| Embedding model | Same H6.1 locator with EmbeddingGemma vs Qwen 0.6B vs Qwen 4B vs any Gemma/code embedding candidate, measured on identical retrieval configs. |
| Local reranker model | One-shot rerank-only eval over the same H6.1 candidate set, without giving the model open-ended search control. This should test Gemma E2B/E4B, Qwen3.5, and a specialized Qwen3-Reranker if available. |
| Orchestrator/explainer model | Code-reading answer eval: H6.1 returns files, model reads tools/source, answers question. This needs explanation/helpfulness metrics, not only file Hit@K. |

## Implementation Notes

This run also fixed two agent-loop issues before the 100-case measurements:

- `code_diver_read` now accepts model-produced range strings like `"20-60"` instead
  of failing the tool call.
- Hypotheses named `agent_*` now activate the adaptive/agentic early-stop policy.
  Before this fix, agent runs could keep searching after a successful rerank.

The local-agent run is now measuring the model behavior rather than a broken loop.
