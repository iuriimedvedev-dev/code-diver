# H7 Adaptive Gated Rerank - 2026-06-08

## Question

H7 is the current compact file-level search branch: use the H6.1 calibrated
hybrid file locator, add cheap query-time improvements where they help, and
spend LLM tokens only when they improve ranking.

The concrete question in this pass:

```text
Can we improve H7 by learning when to call an expensive LLM reranker,
instead of always reranking or never reranking?
```

This is different from H8 reranker ensembling. H8 combines rankings after they
exist. H7.3 is a cost-aware selector before reranking: it decides whether the
current deterministic H7 result is confident enough, or whether Gemini Lite
should rerank the candidate files.

## Baseline

The valid H7 baseline for this pass is:

- persistent index: EmbeddingGemma-300M `file_summary` + `file_manifest`;
- no code-body vectors;
- calibrated H6.1 hybrid weights;
- H7.2 lexical query expansion enabled;
- graph only as bounded containment metadata for this profile;
- deterministic output is a ranked file list.

Reference report:

- `.code-diver/reports/h8-train1k-h7-query-expansion-deterministic-1000.json`
- config: `configs/benchmarks/codesearchnet-h7-query-expansion-embeddinggemma-1000.yml`

Full CodeSearchNet/MTEB Python 1,000:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Precision@10 | Mean ms | API cost/1k |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H7 query expansion | 1000 | 0.857 | 0.957 | 0.980 | 0.987 | 0.909 | 0.928 | 0.152 | 780.2 | 0 |
| Gemini Lite rerank always | 1000 | 0.911 | 0.978 | 0.988 | 0.989 | 0.944 | 0.956 | 0.155 | 3487.8 | about 2.93 |

The important readout: H7 already has high candidate recall. Gemini Lite mostly
improves head ordering, not top-10 coverage.

## Hypotheses

| ID | Hypothesis | Status | Decision |
| --- | --- | --- | --- |
| `H7.1` | Add compact API manifest vectors per file. | active, not default | Useful as agent/reranker context; deterministic fusion did not use it well. |
| `H7.2` | Expand only lexical query terms with aliases. | active, not sufficient | Cheap and safe to keep in configs, but not a universal quality win. |
| `H7.3` | Learn a gate that calls LLM rerank only on low-confidence H7 results. | active candidate | Best current H7 improvement direction because it trades quality, latency, and API cost explicitly. |
| `H7.4` | Add richer non-leaking confidence features to the gate. | implemented in analysis script | Improved the gate signal versus margin-only; still not enough to hit oracle consistently. |
| `H7.5` | Route-specific gate thresholds. | tested, active fallback | Cheaper than MLP/logistic gates, but lower quality. Useful as an interpretable fallback, not the winner. |
| `H7.6` | Replace Gemini Lite inside the gate with a local cross-encoder or small local LLM reranker. | proposed | Needed to remove API cost; must be compared on the same gate protocol. |
| `H7.7` | Route-specific query expansion. | proposed | SWE and CodeSearchNet behavior differ; global aliases are too blunt. |

## What Changed In The Gate

Script:

- `scripts/analyze_h7_gated_rerank.py`

Inputs:

- H7 deterministic report;
- Gemini Lite rerank report over the same cases;
- trace with `hybrid_rank_stages` and `llm_rerank_response` events.

New gate features are intentionally non-leaking. They use only data available
before LLM rerank:

- route: `semantic`, `workflow`, `path_symbol`;
- query length;
- candidate count;
- top score and score gaps;
- top-5/top-10 score mean and standard deviation;
- top-10 score entropy;
- top candidate vector/lexical/path/symbol/graph component scores;
- top candidate item kind;
- vector/lexical/path-symbol agreement rates in top-10;
- graph candidate count/depth/final-result rate.

Models tested:

- fixed threshold policies such as `margin_lt_0.075`;
- logistic gate;
- one-hidden-layer NumPy MLP gate;
- oracle improvement gate as a label-leaking upper bound.

Utility used for validation selection:

```text
utility = Hit@1 - 0.01 * mean_seconds - 0.25 * api_cost_per_query_usd
```

The utility is not the product metric. It is a repeatable selector for
quality/latency/cost tradeoffs.

## CodeSearchNet Split Stability

Three random 700/150/150 splits over the same 1,000 saved CodeSearchNet cases:

| Seed | Policy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Rerank call rate | Mean ms | API cost/1k |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 17 | H7 only | 0.827 | 0.967 | 0.980 | 1.000 | 0.894 | 0.921 | 0.000 | 780.2 | 0.000 |
| 17 | Gemini Lite always | 0.907 | 0.980 | 1.000 | 1.000 | 0.944 | 0.958 | 1.000 | 2765.1 | 2.933 |
| 17 | Route threshold gate | 0.873 | 0.987 | 1.000 | 1.000 | 0.928 | 0.947 | 0.293 | 1362.4 | 0.860 |
| 17 | MLP gate | 0.913 | 0.987 | 1.000 | 1.000 | 0.949 | 0.962 | 0.260 | 1296.3 | 0.763 |
| 17 | Oracle gate | 0.920 | 0.987 | 1.000 | 1.000 | 0.953 | 0.965 | 0.107 | 991.9 | 0.313 |
| 23 | H7 only | 0.887 | 0.947 | 0.973 | 0.987 | 0.922 | 0.938 | 0.000 | 780.2 | 0.000 |
| 23 | Gemini Lite always | 0.953 | 0.987 | 0.987 | 0.987 | 0.969 | 0.973 | 1.000 | 2765.1 | 2.933 |
| 23 | Route threshold gate | 0.913 | 0.953 | 0.980 | 0.987 | 0.939 | 0.950 | 0.107 | 991.9 | 0.313 |
| 23 | Logistic gate | 0.947 | 0.980 | 0.987 | 0.987 | 0.964 | 0.970 | 0.327 | 1428.6 | 0.958 |
| 23 | MLP gate | 0.947 | 0.980 | 0.987 | 0.987 | 0.964 | 0.970 | 0.400 | 1574.2 | 1.173 |
| 23 | Oracle gate | 0.953 | 0.987 | 0.987 | 0.987 | 0.969 | 0.973 | 0.080 | 939.0 | 0.235 |
| 42 | H7 only | 0.880 | 0.967 | 0.993 | 0.993 | 0.927 | 0.944 | 0.000 | 780.2 | 0.000 |
| 42 | Gemini Lite always | 0.900 | 0.980 | 1.000 | 1.000 | 0.940 | 0.955 | 1.000 | 2765.1 | 2.933 |
| 42 | Route threshold gate | 0.893 | 0.973 | 1.000 | 1.000 | 0.935 | 0.951 | 0.247 | 1269.8 | 0.724 |
| 42 | MLP gate | 0.900 | 0.973 | 1.000 | 1.000 | 0.938 | 0.954 | 0.307 | 1388.9 | 0.900 |
| 42 | Oracle gate | 0.920 | 0.987 | 1.000 | 1.000 | 0.954 | 0.965 | 0.053 | 886.1 | 0.156 |

Interpretation:

- The gate signal is real: learned gates improve Hit@1/nDCG over H7-only on
  all three splits.
- The MLP/logistic gates are still imperfect: they sometimes spend 3-5x more
  LLM calls than the oracle for similar or lower quality.
- The oracle ceiling is close to always-Gemini quality while using only
  `5-11%` of rerank calls. That is the main opportunity.
- The best current gate is not yet a default replacement because split results
  vary and the gate is trained on saved Gemini rerank outputs, not integrated
  into live search.
- Route threshold gates are useful but not sufficient. They improve H7-only
  with low cost, especially on seed 23, but they leave quality behind
  logistic/MLP gates because the decision needs score-shape features inside
  each route.

## Route Diagnostics

The route bucket diagnostics are computed over all 1,000 CodeSearchNet cases
before the random split:

| Route | Cases | H7 Hit@1 | Gemini Hit@1 | Gemini improvement rate | Margin mean | Margin p50 | Margin p90 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `path_symbol` | 468 | 0.863 | 0.921 | 0.085 | 0.196 | 0.180 | 0.392 |
| `semantic` | 216 | 0.787 | 0.847 | 0.116 | 0.176 | 0.156 | 0.362 |
| `workflow` | 316 | 0.896 | 0.940 | 0.066 | 0.167 | 0.158 | 0.324 |

Interpretation:

- `semantic` is the weakest H7 bucket and has the highest rerank improvement
  rate, so it should get the most permissive rerank policy.
- `workflow` has the best H7 Hit@1 and lowest improvement rate, so broad
  always-rerank policies waste calls there.
- `path_symbol` still benefits from Gemini even though it looks exact-match
  heavy, so hard-disabling rerank by route is too blunt.
- Margin alone is not enough: the margin distributions overlap too much across
  routes. The gate needs score-shape and agreement features.

## SWEbenchCodeRetrieval Check

The public SWE 100-case smoke remains a useful harder ranking check.

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Precision@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H6.1 EmbeddingGemma | 100 | 0.610 | 0.810 | 0.920 | 0.960 | 0.717 | 0.804 | 0.185 | not strict |
| H7.2 query expansion | 100 | 0.610 | 0.810 | 0.920 | 0.960 | 0.717 | 0.804 | 0.185 | 209.8 |
| H9 body evidence | 100 | 0.610 | 0.790 | 0.870 | 0.940 | 0.725 | 0.796 | 0.248 | not strict |

Interpretation:

- Global H7 aliases do not transfer to SWE.
- SWE has high top-10 but weak Hit@1, so it is a better benchmark for the next
  rerank/gate iteration than another index-lane experiment.
- H9 raises precision but hurts Hit@5/10, so body evidence should remain gated.

## Decision

H7.3/H7.4 are the best H7 improvement direction so far, but not production
default yet.

Promote the idea, not this exact model:

```text
H7 candidate generator
-> confidence/gate model
-> call expensive reranker only when the gate predicts useful movement
```

Do not promote:

- always-on extra body-evidence lane;
- always-on API manifest lane in deterministic fusion;
- global lexical aliases as a claimed universal improvement;
- open-ended agentic search as the default.

## Next Experiments

1. Train the gate on a larger sample with explicit validation by dataset:
   CodeSearchNet train, SWE validation, repo-local e2e holdout.
2. Add raw candidate-level score features from the hybrid search service
   directly instead of reconstructing them from traces.
3. Replace Gemini Lite in the gated slot with:
   - Qwen3-Reranker cross-encoder;
   - Gemma local rerank prompt only for low-confidence cases;
   - Gemini Lite only as quality/cost reference.
4. Add route-specific thresholds:
   - `path_symbol` queries often need exact matching;
   - `workflow` queries need broader rerank/probes;
   - `semantic` queries need stronger natural-language rerank.
5. Add a production guard:
   - never demote deterministic H7 top-1 when confidence is high;
   - keep top-10 candidate set monotonic unless the reranker provides a
     calibrated confidence reason.

## Commands

Reproduce the gate simulation:

```bash
uv run python scripts/analyze_h7_gated_rerank.py \
  --seed 17 \
  --base-report .code-diver/reports/h8-train1k-h7-query-expansion-deterministic-1000.json \
  --rerank-report .code-diver/reports/h8-train1k-gemini-lite-rerank-1000.json \
  --trace .code-diver/traces/codesearchnet-h8-gemini-lite-rerank-1000.jsonl \
  --output .code-diver/reports/h7-gated-gemini-lite-seed17-train700-val150-test150.json
```

Run the SWE H7 transfer check:

```bash
uv run code-diver evaluate \
  --config configs/benchmarks/swebench-h7-query-expansion-embeddinggemma-100.yml \
  --json > .code-diver/reports/swebench-code-retrieval-100-h7-query-expansion-embeddinggemma.json
```
