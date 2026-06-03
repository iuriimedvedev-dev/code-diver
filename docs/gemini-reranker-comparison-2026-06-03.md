# Gemini Reranker Comparison - 2026-06-03

This is an interim comparison from saved artifacts only. No new evaluation was run for this report.

Compared models:

- `gemini-3.5-flash`
- `gemini-3.1-flash-lite`

## Executive Summary

Gemini 3.5 Flash is the stronger reranker when the ranking position matters, especially Hit@1, MRR, and nDCG.

Gemini 3.1 Flash-Lite is the better cost/value model: it often preserves almost the same Hit@10 and Recall@10, while costing roughly 5-7x less in the saved IntelliJ runs.

The practical conclusion:

- Use Gemini 3.5 Flash as the oracle / quality ceiling / hard-case adjudicator.
- Use Gemini 3.1 Flash-Lite for cheap API comparison runs.
- Use local cross-encoder rerankers for full iterative sweeps.

## Comparable Answer-Set Runs

Dataset: `datasets/intellij_eval_1000.answer_sets.jsonl`.

These are the fairest full 1000-case comparisons currently saved for H2 branch A and branch B.

| Scenario | Model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | p95 ms | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H2 A grep/read | Gemini 3.5 Flash | 1000 | 0.785 | 0.868 | 0.875 | 0.882 | 0.861 | 0.112 | 0.826 | 0.820 | 3190 | 5675 | $12.78 |
| H2 A grep/read | Gemini 3.1 Flash-Lite | 1000 | 0.719 | 0.859 | 0.875 | 0.883 | 0.864 | 0.114 | 0.790 | 0.796 | 2851 | 5153 | $2.03 |
| H2 B ephemeral index | Gemini 3.5 Flash | 1000 | 0.778 | 0.858 | 0.859 | 0.869 | 0.849 | 0.111 | 0.817 | 0.810 | 6389 | 11296 | $14.22 |
| H2 B ephemeral index | Gemini 3.1 Flash-Lite | 1000 | 0.738 | 0.845 | 0.857 | 0.866 | 0.846 | 0.111 | 0.792 | 0.792 | 6390 | 11387 | $2.26 |

Answer-set deltas, Gemini 3.5 Flash minus Gemini 3.1 Flash-Lite:

| Scenario | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | Cost ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H2 A grep/read | +0.066 | +0.009 | +0.000 | -0.001 | -0.003 | +0.036 | +0.024 | +339 | 6.3x |
| H2 B ephemeral index | +0.040 | +0.013 | +0.002 | +0.003 | +0.003 | +0.025 | +0.018 | -1 | 6.3x |

Interpretation:

- Flash-Lite nearly matches top-k coverage.
- Gemini 3.5 is materially better at putting the right answer first.
- On these two H2 branches, Gemini 3.5 buys +4.0 to +6.6 Hit@1 points and +2.5 to +3.6 MRR points for about 6.3x cost.

## Comparable Strict Runs

Dataset: older strict IntelliJ 1000-case runs. These numbers are useful for trend analysis, but they should not be mixed directly with answer-set metrics.

| Scenario | Model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | p95 ms | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H2 A grep/read | Gemini 3.5 Flash | 1000 | 0.735 | 0.827 | 0.840 | 0.856 | 0.856 | 0.086 | 0.785 | 0.802 | 3070 | 5118 | $13.51 |
| H2 A grep/read | Gemini 3.1 Flash-Lite | 1000 | 0.700 | 0.815 | 0.828 | 0.850 | 0.850 | 0.085 | 0.760 | 0.783 | 2319 | 4419 | $2.16 |
| H2 B ephemeral index | Gemini 3.5 Flash | 1000 | 0.562 | 0.601 | 0.621 | 0.635 | 0.635 | 0.218 | 0.585 | 0.606 | 8436 | 13935 | $14.03 |
| H2 B ephemeral index | Gemini 3.1 Flash-Lite | 1000 | 0.530 | 0.595 | 0.608 | 0.630 | 0.630 | 0.202 | 0.563 | 0.588 | 7301 | 12677 | $2.28 |
| H3 union | Gemini 3.5 Flash | 1000 | 0.758 | 0.799 | 0.842 | 0.863 | 0.863 | 0.226 | 0.788 | 0.817 | 5557 | 11368 | $32.72 |
| H3 union | Gemini 3.1 Flash-Lite | 1000 | 0.690 | 0.793 | 0.826 | 0.861 | 0.861 | 0.183 | 0.747 | 0.784 | 7698 | 18962 | $5.33 |

Strict-run deltas, Gemini 3.5 Flash minus Gemini 3.1 Flash-Lite:

| Scenario | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | Cost ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H2 A grep/read | +0.035 | +0.012 | +0.012 | +0.006 | +0.006 | +0.025 | +0.019 | +751 | 6.3x |
| H2 B ephemeral index | +0.032 | +0.006 | +0.013 | +0.005 | +0.005 | +0.022 | +0.018 | +1135 | 6.2x |
| H3 union | +0.068 | +0.006 | +0.016 | +0.002 | +0.002 | +0.041 | +0.033 | -2141 | 6.1x |

Interpretation:

- The same pattern repeats: Gemini 3.5 improves first-rank quality more than broad top-k coverage.
- On H3 union, Gemini 3.5 is both higher quality and faster in this saved run, but much more expensive.
- The old strict labels understate some multi-answer workflows, so answer-set metrics should be preferred for current decisions.

## Partial H4 Multi-Query Runs

These runs are only 175/1000 cases, so treat them as directional.

| Scenario | Model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | p95 ms | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 multi-query | Gemini 3.5 Flash | 175/1000 | 0.714 | 0.800 | 0.857 | 0.863 | 0.863 | 0.227 | 0.764 | 0.801 | 12744 | 20747 | $5.82 |
| H4 multi-query | Gemini 3.1 Flash-Lite | 175/1000 | 0.657 | 0.800 | 0.834 | 0.869 | 0.869 | 0.173 | 0.730 | 0.776 | 12745 | 19049 | $0.95 |

Partial H4 delta:

| Scenario | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | Cost ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H4 multi-query | +0.057 | +0.000 | +0.023 | -0.006 | -0.006 | +0.034 | +0.025 | -1 | 6.1x |

## Non-Comparable Quality Ceiling

The strongest saved Gemini 3.5 result does not currently have a completed Gemini 3.1 Flash-Lite counterpart on the exact same H3 manifest answer-set setup.

| Scenario | Model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | p95 ms | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest, answer-set v2 | Gemini 3.5 Flash | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.419 | 0.898 | 0.908 | 6542 | 9285 | $34.94 |

This is the current measured quality ceiling. It should remain the oracle baseline until a local or cheaper API setup beats it on the same 1000-case answer-set eval.

## Current Conclusion

Gemini 3.5 Flash is probably the best API reranker we have measured so far. The value is concentrated in ranking sharpness:

- It consistently improves Hit@1.
- It consistently improves MRR and nDCG.
- It does not usually improve Hit@10 much over Flash-Lite, because candidate recall is already mostly solved by the upstream retrieval stage.

Gemini 3.1 Flash-Lite is still useful. It is much cheaper and often enough when we only care about top-k candidate coverage.

For the next full comparison table, add:

1. H3 manifest + Gemini 3.1 Flash-Lite on the same answer-set dataset.
2. H3 manifest + local Qwen3-Reranker 0.6B and 4B.
3. A confidence-gated cascade: local reranker first, Gemini 3.5 only on low-margin or disputed cases.
