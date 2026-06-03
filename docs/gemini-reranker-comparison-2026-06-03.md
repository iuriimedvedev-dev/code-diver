# Gemini H3 Reranker Comparison - 2026-06-03

This is an interim H3-only comparison from saved artifacts. No new evaluation was run for this report.

Compared models:

- `gemini-3.5-flash`
- `gemini-3.1-flash-lite`

Important scope correction: H2 is obsolete for the current architecture and is intentionally excluded from the main comparison. The active decision path is H3 and later successors.

## Executive Summary

On the H3 data we have, Gemini 3.5 Flash is the stronger reranker when first-rank quality matters.

Gemini 3.1 Flash-Lite remains interesting as a cheaper API baseline, but the saved H3 runs show the same pattern as before: Flash-Lite keeps broad top-k coverage close, while Gemini 3.5 is better at ordering the best answer first.

Current practical conclusion:

- Use Gemini 3.5 Flash as the H3 oracle / quality ceiling / hard-case adjudicator.
- Do not spend more money on legacy H2 comparisons.
- The missing fair comparison is `H3 manifest + Gemini 3.1 Flash-Lite` on the same answer-set dataset as the current Gemini 3.5 ceiling.
- Local Qwen3 cross-encoder rerankers should be optimized against the H3 Gemini 3.5 ceiling, not against H2.

## H3 Head-To-Head: Union Strict Eval

Dataset: older strict IntelliJ 1000-case eval.

This is the only completed 1000-case H3 head-to-head currently saved for Gemini 3.5 Flash vs Gemini 3.1 Flash-Lite.

| Scenario | Model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | p95 ms | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 union | Gemini 3.5 Flash | 1000 | 0.758 | 0.799 | 0.842 | 0.863 | 0.863 | 0.226 | 0.788 | 0.817 | 5557 | 11368 | $32.72 |
| H3 union | Gemini 3.1 Flash-Lite | 1000 | 0.690 | 0.793 | 0.826 | 0.861 | 0.861 | 0.183 | 0.747 | 0.784 | 7698 | 18962 | $5.33 |

Delta, Gemini 3.5 Flash minus Gemini 3.1 Flash-Lite:

| Scenario | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | Cost ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 union | +0.068 | +0.006 | +0.016 | +0.002 | +0.002 | +0.043 | +0.041 | +0.033 | -2141 | 6.1x |

Interpretation:

- Hit@10 is effectively tied: `0.863` vs `0.861`.
- Hit@1 is not tied: Gemini 3.5 wins by `+6.8` points.
- MRR and nDCG also move meaningfully in favor of Gemini 3.5.
- This means candidate recall is already mostly solved at H3 union level; the model difference is primarily rank ordering.
- The strict dataset is not the preferred current benchmark, but this remains a valid H3 model-vs-model comparison.

## H3 Quality Ceiling: Manifest Answer-Set Eval

Dataset: `datasets/intellij_eval_1000.answer_sets.jsonl`.

This is the current best saved result and the relevant quality ceiling.

| Scenario | Model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | p95 ms | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest, answer-set v2 | Gemini 3.5 Flash | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.419 | 0.898 | 0.908 | 6542 | 9285 | $34.94 |

This result does not yet have a completed Gemini 3.1 Flash-Lite counterpart on the exact same H3 manifest answer-set setup. Until that run exists, we should not claim a final H3 manifest head-to-head between Gemini 3.5 and Flash-Lite.

Still, this H3 manifest result is the number that matters for current architecture decisions:

- It is the best measured API reranker result.
- It beats the project target of Hit@10 `0.95`.
- It is strong on Hit@5: `0.943`.
- It is strong on first-rank ordering: Hit@1 `0.871`, MRR `0.898`.
- It is expensive enough that we should not use it for routine full sweeps.

## H3 Current Local Reference

The active local H3 + Qwen3-Reranker 0.6B run is still partial, but it is already useful as a zero-API-cost reference.

| Scenario | Model | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Mean ms | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest union CE | Qwen3-Reranker 0.6B local | 450/1000 | 0.747 | 0.936 | 0.947 | 0.962 | 0.840 | 0.841 | 3791 | $0 |

Interpretation:

- Local CE is already near the Gemini 3.5 ceiling on Hit@5 and Hit@10.
- Local CE is still materially behind on Hit@1 and MRR.
- The remaining quality problem is ranking sharpness, not broad recall.

## Current H3-Only Conclusion

Gemini 3.5 Flash is the best measured H3 reranker right now.

The strongest evidence is:

1. On completed H3 union head-to-head, Gemini 3.5 beats Flash-Lite by `+6.8` Hit@1, `+4.1` MRR, and `+3.3` nDCG points while Hit@10 is almost identical.
2. On H3 manifest answer-set, Gemini 3.5 reaches the current ceiling: Hit@1 `0.871`, Hit@5 `0.943`, Hit@10 `0.976`, MRR `0.898`, nDCG `0.908`.
3. The local Qwen3-Reranker path is good enough for cheap iteration, but it has not yet matched Gemini 3.5 on first-rank quality.

Next H3-only comparisons to run:

1. `H3 manifest + Gemini 3.1 Flash-Lite` on `datasets/intellij_eval_1000.answer_sets.jsonl`.
2. `H3 manifest + Qwen3-Reranker 0.6B` full 1000-case final.
3. `H3 manifest + Qwen3-Reranker 4B` full 1000-case final.
4. Confidence cascade: local Qwen3 reranker first, Gemini 3.5 only for low-margin cases.

## Archived Context

H2 results are deliberately not included here. They are useful only as historical debugging context for the grep/read and ephemeral-index branches. They should not guide the current model choice.
