# Gemma 4 Local Rerank Matrix - 2026-06-06

## Goal

Test whether local Gemma 4 models improve H6.1 candidate ranking when the
retrieval index and candidate generator are fixed.

This is a rerank-only experiment:

```text
query
-> H6.1 EmbeddingGemma file locator
-> top structured file candidates
-> optional local Gemma 4 listwise rerank
-> ranked file list
```

It is not the full code-answering agent. The agent path still adds bounded
outline/symbol/rg/grep/read over the selected files and then produces the final
code explanation.

## Fixed Variables

| Axis | Value |
| --- | --- |
| Dataset | CodeSearchNet/MTEB Python public benchmark slice |
| Index | `.code-diver/benchmarks/mteb-codesearchnet-python/index-h5-embeddinggemma-300m-quality.json` |
| Embedding model | `google/embeddinggemma-300m` |
| Candidate generator | H6.1 calibrated hybrid file locator |
| Candidate item type | File metadata only: summaries and manifests, not full code chunks |
| Retrieval target | File path |
| API use | None; local models only |
| Direct API cost | `$0` |

## Compared Strategies

| Strategy | Meaning |
| --- | --- |
| `h6_1_static_no_llm` | H6.1 deterministic candidate order, no LLM rerank. |
| `gemma4_e2b_rerank_after_precision` | Gemma 4 E2B reranks after H6.1 candidate generation, strict precision mode. |
| `gemma4_e4b_rerank_after_precision` | Gemma 4 E4B reranks after H6.1 candidate generation, strict precision mode. |
| `gemma4_e2b_rerank_after_base_prior` | Gemma 4 E2B reranks after H6.1, but preserves the H6.1 top candidate when the score margin is strong. |
| `gemma4_e4b_rerank_after_base_prior` | Gemma 4 E4B reranks after H6.1, but preserves the H6.1 top candidate when the score margin is strong. |

In the current runner, "after" means after deterministic H6.1 candidate
generation. There is no separate pre-retrieval rerank stage; a true "before"
variant would be a different agentic query-planning experiment.

## 10-Case Smoke

| Strategy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Duration ms | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `h6_1_static_no_llm` | 0.7000 | 0.8000 | 1.0000 | 1.0000 | 0.1500 | 1.0000 | 0.8000 | 0.8492 | 2293.4348 | 15915.5268 | 22938.5247 | 0 |
| `gemma4_e2b_rerank_after_precision` | 0.7000 | 0.9000 | 1.0000 | 1.0000 | 0.1500 | 1.0000 | 0.8083 | 0.8562 | 3519.5632 | 4338.8194 | 35198.2446 | 0 |
| `gemma4_e4b_rerank_after_precision` | 0.7000 | 0.8000 | 1.0000 | 1.0000 | 0.1500 | 1.0000 | 0.8000 | 0.8492 | 7507.5242 | 8406.0835 | 75078.0066 | 0 |
| `gemma4_e2b_rerank_after_base_prior` | 0.7000 | 1.0000 | 1.0000 | 1.0000 | 0.1500 | 1.0000 | 0.8167 | 0.8631 | 3712.3804 | 4523.0879 | 37126.3157 | 0 |
| `gemma4_e4b_rerank_after_base_prior` | 0.7000 | 0.8000 | 1.0000 | 1.0000 | 0.1500 | 1.0000 | 0.8000 | 0.8492 | 7360.2415 | 8011.4307 | 73604.9638 | 0 |

## 100-Case Slice

| Strategy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Duration ms | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `h6_1_static_no_llm` | 0.8200 | 0.9300 | 0.9700 | 0.9700 | 0.1470 | 0.9700 | 0.8762 | 0.8996 | 885.9212 | 940.6032 | 88615.7287 | 0 |
| `gemma4_e2b_rerank_after_precision` | 0.8100 | 0.9500 | 0.9700 | 0.9700 | 0.1470 | 0.9700 | 0.8767 | 0.9004 | 3461.8860 | 4112.6981 | 346212.9040 | 0 |
| `gemma4_e4b_rerank_after_precision` | 0.8300 | 0.9300 | 0.9700 | 0.9700 | 0.1470 | 0.9700 | 0.8828 | 0.9046 | 7480.2977 | 8402.0119 | 748053.7883 | 0 |
| `gemma4_e2b_rerank_after_base_prior` | 0.8200 | 0.9400 | 0.9600 | 0.9700 | 0.1470 | 0.9700 | 0.8788 | 0.9020 | 3570.1158 | 4252.2644 | 357035.6640 | 0 |
| `gemma4_e4b_rerank_after_base_prior` | 0.8400 | 0.9300 | 0.9700 | 0.9700 | 0.1470 | 0.9700 | 0.8895 | 0.9096 | 7455.9322 | 8380.1994 | 745617.7687 | 0 |

## Current Interpretation

The 10-case smoke only proves the fixed local Gemma JSON-schema path is stable.
The 100-case slice is the first useful signal:

- Gemma 4 E4B base-prior produced the best 100-case Hit@1, MRR, and nDCG.
- The quality lift is small: Hit@1 `0.84` vs `0.82`, nDCG `0.9096` vs `0.8996`.
- The latency cost is large: about `7.46s/query` vs `0.89s/query`.
- Gemma 4 E2B precision mode slightly hurts Hit@1 and is not a default reranker.
- Conservative/base-prior rerank is safer than unconstrained precision rerank for
  small local models, because H6.1 already has a strong first candidate.

Because CodeSearchNet has one expected file per query in this slice,
`Precision@10` mostly follows list length and is not the decisive metric here.
For this rerank-only stage, the useful metrics are Hit@1/3/5/10, MRR, nDCG, and
latency.

## 200-Case Run

| Strategy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Duration ms | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `h6_1_static_no_llm` | 0.8000 | 0.9350 | 0.9700 | 0.9750 | 0.1510 | 0.9750 | 0.8695 | 0.8960 | 872.3339 | 909.9932 | 174516.0223 | 0 |
| `gemma4_e2b_rerank_after_precision` | 0.7800 | 0.9450 | 0.9700 | 0.9750 | 0.1510 | 0.9750 | 0.8623 | 0.8909 | 3619.4790 | 4320.8670 | 723947.3183 | 0 |
| `gemma4_e4b_rerank_after_precision` | 0.8050 | 0.9350 | 0.9700 | 0.9750 | 0.1510 | 0.9750 | 0.8729 | 0.8985 | 8865.9248 | 10033.0958 | 1773245.4708 | 0 |
| `gemma4_e2b_rerank_after_base_prior` | 0.7950 | 0.9350 | 0.9650 | 0.9750 | 0.1510 | 0.9750 | 0.8671 | 0.8943 | 3945.6249 | 4715.9921 | 789176.4937 | 0 |
| `gemma4_e4b_rerank_after_base_prior` | 0.8100 | 0.9400 | 0.9700 | 0.9750 | 0.1510 | 0.9750 | 0.8758 | 0.9007 | 8818.8131 | 9908.8833 | 1763820.3530 | 0 |

## Token And Runtime Trace

All model calls in this run used local endpoints. The table below reports token
volume and provider-reported model time; `token_equivalent_cost` is a pricing
signal from the trace, not an external API bill.

### 100 Cases

| Strategy | Calls | Input tokens | Output tokens | Total tokens | Model ms sum | Token-equivalent cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gemma4_e2b_rerank_after_precision` | 100 | 1105821 | 4906 | 1110727 | 268138.6 | 1.702886 |
| `gemma4_e4b_rerank_after_precision` | 100 | 1105821 | 3739 | 1109560 | 670055.5 | 1.692383 |
| `gemma4_e2b_rerank_after_base_prior` | 100 | 1105321 | 6644 | 1111965 | 280047.6 | 1.717777 |
| `gemma4_e4b_rerank_after_base_prior` | 100 | 1105321 | 4336 | 1109657 | 668493.6 | 1.697005 |

### 200 Cases

| Strategy | Calls | Input tokens | Output tokens | Total tokens | Model ms sum | Token-equivalent cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gemma4_e2b_rerank_after_precision` | 200 | 2211825 | 9333 | 2221158 | 560385.6 | 3.401734 |
| `gemma4_e4b_rerank_after_precision` | 200 | 2211825 | 7491 | 2219316 | 1611429.1 | 3.385157 |
| `gemma4_e2b_rerank_after_base_prior` | 200 | 2210825 | 12843 | 2223668 | 628949.8 | 3.431824 |
| `gemma4_e4b_rerank_after_base_prior` | 200 | 2210825 | 8512 | 2219337 | 1601521.3 | 3.392845 |

## 200-Case Interpretation

The 200-case result confirms the 100-case direction, but also shows the effect
size is small:

- Best local reranker: `gemma4_e4b_rerank_after_base_prior`.
- Quality lift over static H6.1: Hit@1 `+0.010`, Hit@3 `+0.005`, MRR `+0.0063`,
  nDCG `+0.0047`.
- Hit@5 and Hit@10 do not improve; H6.1 already keeps the right file in the top
  5/10 for this slice.
- E2B is not a useful local reranker in this setup. Both E2B modes underperform
  static H6.1 on Hit@1, MRR, and nDCG.
- E4B precision mode is marginally positive, but base-prior is safer and better.
- The E4B gain costs roughly `10.1x` mean query latency over static H6.1 on this
  machine (`8818.8ms` vs `872.3ms`).

Current decision: local Gemma 4 E4B base-prior is a valid high-quality local
rerank option, but it is not strong enough to replace static H6.1 as the default
interactive path. It belongs behind a gate: use it for hard/ambiguous queries or
offline quality mode, not for every query.

## Agentic Loop Sanity

After the rerank-only matrix, we ran a separate 10-case local-only agentic sanity
check:

```text
query
-> local Gemma 4 agent generates tool calls
-> H6.1 search / outline / symbols / rg / grep / read / rerank tools
-> ranked file list
```

This measures the search-agent loop, not final explanation quality. It is not
directly comparable to one-shot rerank because the model can issue multiple
searches and tool calls.

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Model calls | Tool calls | Tokens | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemma 4 E2B agentic | 10 | 0.400 | 0.800 | 0.800 | 0.800 | 0.080 | 0.800 | 0.600 | 0.652 | 13837.9 | 22186.8 | 42 | 33 | 315620 | 0 |
| Gemma 4 E4B agentic | 10 | 0.400 | 0.800 | 0.900 | 0.900 | 0.133 | 0.900 | 0.608 | 0.682 | 40129.7 | 64262.5 | 53 | 39 | 322706 | 0 |

The sanity result is negative: free local-agent search is worse than static H6.1
and worse than bounded rerank-only on the same 10-case slice. E4B is better than
E2B on top-k recall, but still loses badly on Hit@1 and latency.

We still launched a 100-case E4B agentic run to verify this is not only 10-case
noise. If that run confirms the drop, the local Gemma agent should not own broad
candidate discovery. It can still be useful later in the product pipeline for
bounded file reading and explanation after H6.1 has already found candidates.

## Agentic Loop 100-Case Result

The 100-case E4B agentic run confirmed the 10-case sanity direction:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Model calls | Tool calls | Tokens | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemma 4 E4B agentic | 100 | 0.480 | 0.720 | 0.780 | 0.780 | 0.154 | 0.780 | 0.602 | 0.647 | 39030.9 | 48536.4 | 510 | 345 | 3132763 | 0 |

Decision: local Gemma 4 E4B should not own broad search/tool planning in the
current contract. It follows JSON/tool protocol, but the free agentic loop loses
too much recall and first-rank quality versus deterministic H6.1 and bounded
rerank-only.

## Gemma 4 12B Runtime Fix

The old 12B attempt used GGUF/llama.cpp and failed the tool protocol. The new
attempt uses MLX 4-bit:

```text
.code-diver/models/mlx-community-gemma-4-12B-it-4bit
```

Runtime findings:

- `mlx-vlm 0.5.0` failed to load the model: `model_type gemma4_unified not supported`.
- upgrading the local runtime to `mlx-vlm 0.6.2` added `gemma4_unified` support;
- the server must be started and queried with the same local model id, otherwise
  `mlx_vlm.server` treats the request as a model switch and reloads from HF;
- JSON Schema smoke passed after using the local model id consistently.

## Gemma 4 12B Rerank 100

Fixed variables are the same as above: H6.1 EmbeddingGemma file locator,
CodeSearchNet Python 100-case slice, top structured file candidates, local-only
listwise rerank. 12B uses base-prior mode.

| Strategy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Duration ms | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `h6_1_static_no_llm` | 0.8200 | 0.9300 | 0.9700 | 0.9700 | 0.1470 | 0.9700 | 0.8762 | 0.8996 | 911.2467 | 894.7714 | 91148.8577 | 0 |
| `gemma4_12b_rerank_after_base_prior` | 0.8500 | 0.9600 | 0.9700 | 0.9800 | 0.1500 | 0.9800 | 0.9042 | 0.9233 | 36815.0337 | 42762.6600 | 3681532.2581 | 0 |

Diagnostics:

| Metric | Value |
| --- | ---: |
| Rerank calls | 100 |
| Empty `selected_indices` | 37 |
| Empty rate | 0.37 |
| Total tokens | 1113990 |
| Model ms sum | 3599636.3 |

Interpretation:

- 12B is the best local rerank quality measured so far on this 100-case slice:
  Hit@1 `0.850`, MRR `0.904`, nDCG `0.923`.
- It is not interactive: mean latency is `36.8s/query`.
- The model frequently emits semantically empty structured selections. The
  current base-prior/preserve-top behavior prevents catastrophic loss, but this
  should become an explicit guard: empty rerank output must preserve the H6.1
  order and be counted as a model-contract failure.
- A raw 200-case 12B rerank run is in progress before applying any guard, so the
  100/200 comparison stays honest.
