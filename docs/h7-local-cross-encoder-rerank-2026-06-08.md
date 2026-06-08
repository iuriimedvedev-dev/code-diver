# H7 Local Cross-Encoder Rerank - 2026-06-08

## Purpose

Continue the local-only H7 rerank line with a dedicated reranker instead of a
generative Gemma listwise prompt.

Tested model:

- `Qwen3-Reranker-0.6B-Q4_K_M.gguf`;
- served by llama.cpp `/v1/rerank`;
- H7/H6.1 EmbeddingGemma file-level candidates;
- no code-body vectors.

## Existing 100-Case Result

Saved report:

- `.code-diver/reports/codesearchnet-h6-embeddinggemma-reranker-100.json`
- trace: `.code-diver/traces/codesearchnet-h6-embeddinggemma-reranker-100.jsonl`

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H7/H6.1 static | 100 | 0.810 | 0.920 | 0.960 | 0.970 | 0.875 | 0.899 | 867 | 860 |
| Qwen3-Reranker 0.6B always-on | 100 | 0.780 | 0.930 | 0.980 | 0.990 | 0.862 | 0.896 | 2881 | 5063 |

Interpretation:

- Qwen3-Reranker 0.6B improves tail recall/ranking: Hit@5 and Hit@10 go up.
- It hurts head ranking: Hit@1 and MRR go down.
- Therefore it is not a default always-on reranker.
- It is a candidate for gated low-confidence rerank.

## Gated Split Results

The gate analysis uses 60/20/20 random splits over the same saved 100 cases.

### Unguarded Qwen3-Reranker 0.6B

| Seed | Policy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Call rate | Mean ms |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 17 | H7 only | 0.800 | 0.900 | 0.900 | 0.900 | 0.850 | 0.863 | 0.000 | 867 |
| 17 | Qwen always | 0.800 | 0.850 | 0.950 | 0.950 | 0.850 | 0.875 | 1.000 | 2881 |
| 17 | Qwen oracle gate | 0.800 | 0.900 | 0.950 | 0.950 | 0.863 | 0.885 | 0.050 | 968 |
| 17 | Qwen logistic gate | 0.800 | 0.900 | 0.950 | 0.950 | 0.863 | 0.885 | 0.200 | 1270 |
| 23 | H7 only | 0.850 | 0.950 | 1.000 | 1.000 | 0.912 | 0.935 | 0.000 | 867 |
| 23 | Qwen always | 0.700 | 1.000 | 1.000 | 1.000 | 0.833 | 0.876 | 1.000 | 2881 |
| 23 | Qwen oracle gate | 0.850 | 1.000 | 1.000 | 1.000 | 0.917 | 0.938 | 0.050 | 968 |
| 42 | H7 only | 0.800 | 1.000 | 1.000 | 1.000 | 0.900 | 0.926 | 0.000 | 867 |
| 42 | Qwen always | 0.750 | 0.950 | 1.000 | 1.000 | 0.854 | 0.891 | 1.000 | 2881 |
| 42 | Qwen oracle gate | 0.800 | 1.000 | 1.000 | 1.000 | 0.900 | 0.926 | 0.000 | 867 |

### Simulated Preserve-Top Guard

The saved Qwen run used `preserve_top_candidate: false`. The analyzer now
supports `--rerank-preserve-top-margin`, which simulates preserving the H7
top-1 when the H7 score margin is at least a threshold. The first tested value
is `0.03`, matching the H7 vector-top guard.

| Seed | Policy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Call rate | Mean ms |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 17 | H7 only | 0.800 | 0.900 | 0.900 | 0.900 | 0.850 | 0.863 | 0.000 | 867 |
| 17 | Qwen preserve always | 0.800 | 0.850 | 0.950 | 0.950 | 0.850 | 0.875 | 1.000 | 2881 |
| 17 | Qwen preserve oracle gate | 0.800 | 0.900 | 0.950 | 0.950 | 0.863 | 0.885 | 0.050 | 968 |
| 23 | H7 only | 0.850 | 0.950 | 1.000 | 1.000 | 0.912 | 0.935 | 0.000 | 867 |
| 23 | Qwen preserve always | 0.800 | 1.000 | 1.000 | 1.000 | 0.892 | 0.920 | 1.000 | 2881 |
| 23 | Qwen preserve oracle gate | 0.850 | 1.000 | 1.000 | 1.000 | 0.917 | 0.938 | 0.050 | 968 |
| 42 | H7 only | 0.800 | 1.000 | 1.000 | 1.000 | 0.900 | 0.926 | 0.000 | 867 |
| 42 | Qwen preserve always | 0.800 | 0.950 | 1.000 | 1.000 | 0.871 | 0.903 | 1.000 | 2881 |
| 42 | Qwen preserve oracle gate | 0.800 | 1.000 | 1.000 | 1.000 | 0.900 | 0.926 | 0.000 | 867 |

Interpretation:

- Preserve-top reduces some top-1 damage, but does not make Qwen 0.6B a safe
  always-on reranker.
- The useful signal is sparse: oracle call rate is `0-5%` on these splits.
- The best production shape is `gate -> cross-encoder -> monotonic guard`, not
  blanket cross-encoder rerank.

## Added Config

New reproducible config:

- `configs/benchmarks/codesearchnet-h7-qwen3-reranker-0_6b-preserve-100.yml`

It uses:

- H7 query expansion;
- `cross_encoder_rerank`;
- `Qwen3-Reranker-0.6B-Q4_K_M.gguf`;
- `preserve_top_candidate: true`;
- `preserve_top_score_margin: 0.03`.
- `skip_when_top_margin_at_least: 0.03`.

## Live Gate

Implemented in `CrossEncoderRerankRetrievalStrategy`:

- if H7 top-1 margin is at least `skip_when_top_margin_at_least`, return the
  H7 order without calling the reranker;
- emit `cross_encoder_rerank_skipped` with the margin, threshold, candidate
  count, and preserved top path;
- otherwise call the local cross-encoder and still apply `preserve_top_candidate`
  as a monotonic guard after rerank.

This is the production shape from the offline analysis: cheap H7 for confident
queries, local cross-encoder only for low-confidence/tail cases.

## Decision

Keep Qwen3-Reranker 0.6B as an active local cross-encoder candidate, but only
behind a gate. Do not use it always-on.

Next:

1. Run the new live gate config when the llama.cpp rerank server is up.
2. Test candidate limits `3`, `5`, `10`, and `30`.
3. Test Qwen3-Reranker 4B with the same protocol.
4. Promote the best gate/candidate-limit pair into the default quality config
   only if it improves Hit@3/Hit@5 without hurting Hit@1.
