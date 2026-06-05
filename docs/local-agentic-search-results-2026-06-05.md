# Local Agentic Search Results - 2026-06-05

## Question

Can Code Diver run the search intelligence layer fully locally, and how does that
compare with the main baseline: H6.1 local locator plus Gemini 3.1 Flash Lite?

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
use, and successful early-stop after rerank. It does not work as a primary search
strategy yet. It loses `0.33 Hit@5` and `0.304 nDCG@10` versus H6.1 static, while
being roughly `13x` slower.

Gemini 3.1 Flash Lite is a much stronger intelligence layer than Gemma E2B. It
raises Precision@10 from `0.147` to `0.277`, which means it returns a narrower,
more curated list. But that precision comes at the wrong cost for broad search:
Hit@10 drops from `0.970` to `0.860`.

The current policy is therefore:

1. Keep **H6.1 static** as the default broad search path.
2. Use **Gemini 3.1 Flash Lite** as a gated precision/rerank/explanation layer,
   not as an unrestricted agent loop for every query.
3. Keep **Gemma E2B** as a local runtime candidate for explanation or offline
   hard-tail rerank experiments, not default interactive search.

## Implementation Notes

This run also fixed two agent-loop issues before the 100-case measurements:

- `code_diver_read` now accepts model-produced range strings like `"20-60"` instead
  of failing the tool call.
- Hypotheses named `agent_*` now activate the adaptive/agentic early-stop policy.
  Before this fix, agent runs could keep searching after a successful rerank.

The local-agent run is now measuring the model behavior rather than a broken loop.
