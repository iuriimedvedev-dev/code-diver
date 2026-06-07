# Reranker Ensemble Test - 2026-06-07

## Question

Can we combine several saved reranker outputs the same way we combine hybrid retrieval signals: multiple rankers, weights, and calibration?

## Data

This is an offline test over saved 100-case CodeSearchNet/MTEB Python slice reports. No model/API calls were made.

Included final rankings:

| Run | Role |
| --- | --- |
| `h6` | Best deterministic H6.1/H5 file-level hybrid baseline. |
| `h7_tiebreak` | Deterministic H7 API manifest/tie-breaker variant. |
| `h7_query_expansion` | Deterministic H7 query-expansion variant. |
| `gemma_e2b_agent` | Local Gemma E2B agentic ranking output. |
| `gemma_e4b_agent` | Local Gemma E4B agentic ranking output. |
| `gemma_12b_agent` | Local Gemma 12B agentic ranking output. |
| `gemma26_h6_agent` | Gemma 26B-A4B agent over H6.1 candidates. |
| `gemma26_h7_tiebreak_agent` | Gemma 26B-A4B agent over H7.1 candidates. |
| `gemma26_h7_query_expansion_agent` | Gemma 26B-A4B agent over H7.2 candidates. |

Important caveat: these are final file rankings, not raw reranker logits or calibrated confidence scores. The result tests whether there is useful ensemble signal in the saved outputs. It does not yet prove that we should run multiple LLM rankers per live query.

Raw generated report:

```bash
uv run python scripts/analyze_reranker_ensemble.py \
  --report h6=.code-diver/reports/h6-1-deterministic-current-100.json \
  --report h7_tiebreak=.code-diver/reports/h7_api_tie_breaker-deterministic-100.json \
  --report h7_query_expansion=.code-diver/reports/h7-query-expansion-deterministic-100.json \
  --report gemma_e2b_agent=.code-diver/reports/agentic-strict-gemma4-e2b-qat-llama-ctx16k-100.json \
  --report gemma_e4b_agent=.code-diver/reports/agentic-strict-gemma4-e4b-qat-llama-ctx16k-100.json \
  --report gemma_12b_agent=.code-diver/reports/agentic-strict-gemma4-12b-qat-llama-ctx16k-100.json \
  --report gemma26_h6_agent=.code-diver/reports/agentic-strict-gemma4-26b-a4b-qat-llama-ctx16k-100.json \
  --report gemma26_h7_tiebreak_agent=.code-diver/reports/h7-api-tiebreaker-agentic-gemma4-26b-a4b-qat-100.json \
  --report gemma26_h7_query_expansion_agent=.code-diver/reports/h7-query-expansion-agentic-gemma4-26b-a4b-qat-100.json \
  --output .code-diver/reports/reranker-ensemble-all-saved-codesearchnet-100.json
```

## Single-Ranker Baseline

| Run | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | MRR@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `h6` | 0.820 | 0.930 | 0.970 | 0.970 | 0.970 | 0.876 | 0.900 |
| `h7_query_expansion` | 0.810 | 0.910 | 0.970 | 0.970 | 0.970 | 0.867 | 0.893 |
| `h7_tiebreak` | 0.800 | 0.930 | 0.970 | 0.970 | 0.970 | 0.866 | 0.892 |
| `gemma26_h7_tiebreak_agent` | 0.760 | 0.820 | 0.860 | 0.900 | 0.900 | 0.805 | 0.828 |
| `gemma26_h7_query_expansion_agent` | 0.730 | 0.840 | 0.850 | 0.900 | 0.900 | 0.788 | 0.815 |
| `gemma26_h6_agent` | 0.710 | 0.810 | 0.840 | 0.900 | 0.900 | 0.768 | 0.799 |
| `gemma_12b_agent` | 0.590 | 0.690 | 0.740 | 0.800 | 0.800 | 0.653 | 0.688 |
| `gemma_e4b_agent` | 0.580 | 0.700 | 0.760 | 0.800 | 0.800 | 0.653 | 0.689 |
| `gemma_e2b_agent` | 0.560 | 0.710 | 0.750 | 0.820 | 0.820 | 0.647 | 0.688 |

## RRF Ensemble

Plain unweighted Reciprocal Rank Fusion did not improve the best deterministic run.

| Ensemble | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `h6 + h7_tiebreak + h7_query_expansion` | 0.820 | 0.930 | 0.970 | 0.970 | 0.876 | 0.900 |
| `h6 + h7_tiebreak` | 0.810 | 0.930 | 0.970 | 0.970 | 0.871 | 0.896 |
| `h6 + h7_query_expansion` | 0.810 | 0.930 | 0.970 | 0.970 | 0.871 | 0.896 |
| `h7_tiebreak + h7_query_expansion` | 0.800 | 0.930 | 0.970 | 0.970 | 0.866 | 0.892 |
| `h6 + h7_tiebreak + h7_query_expansion + gemma26_h7_query_expansion_agent` | 0.780 | 0.890 | 0.940 | 0.970 | 0.847 | 0.877 |

Conclusion: naive rank fusion is too blunt. Agentic rankings contain useful recall signal, but equal-weight RRF lets them demote strong deterministic candidates.

## Calibrated Meta-Ranker

The useful variant is a small supervised rank combiner. I trained a 5-fold logistic stacker over per-candidate rank features:

| Feature family | Meaning |
| --- | --- |
| per-run reciprocal rank | `1 / rank` if the file appears in a run, otherwise `0`. |
| per-run normalized rank | Higher when the file appears closer to rank 1. |
| per-run top-1 flag | Whether a run placed the file first. |
| agreement count | Fraction of runs that returned the file. |
| best rank / average rank signal | Whether any run strongly preferred the file. |

Cross-validated results:

| Meta-ranker | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | MRR@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `deterministic_only` | 0.820 | 0.930 | 0.970 | 0.970 | 0.970 | 0.876 | 0.900 |
| `h6_plus_26b_agents` | 0.830 | 0.960 | 0.970 | 0.980 | 0.980 | 0.894 | 0.916 |
| `deterministic_plus_26b_agents` | 0.810 | 0.970 | 0.980 | 0.980 | 0.980 | 0.884 | 0.908 |
| `h6_plus_all_agents` | 0.820 | 0.960 | 0.970 | 0.980 | 0.980 | 0.889 | 0.912 |
| `deterministic_plus_all_agents` | 0.840 | 0.960 | 0.970 | 0.980 | 0.980 | 0.897 | 0.918 |

Oracle best-rank coverage across all saved outputs:

| Oracle metric | Value |
| --- | ---: |
| Hit@1 | 0.940 |
| Hit@3 | 0.980 |
| Hit@5 | 0.980 |
| Hit@10 | 0.990 |

## Decision

This becomes hypothesis `H8`: calibrated reranker ensemble.

Current readout:

- The idea is valid: saved rerankers have complementary signal.
- RRF is not enough and should not be promoted.
- A tiny learned meta-ranker improves the 100-case slice from `h6` Hit@1 `0.820` / Hit@10 `0.970` / nDCG `0.900` to best observed Hit@1 `0.840` / Hit@10 `0.980` / nDCG `0.918`.
- The effect size is promising but still small and based on 100 cases. It needs 1,000+ cases and a strict train/validation/test split before becoming default.
- Running many LLM agents per live query is not practical. The production version should combine cheap rank signals and at most one optional LLM/cross-encoder ranker, then calibrate the stacker offline.

## Next Test

Run `H8` on the 1,000-case slice with:

1. Fixed H6.1/H5 candidate generator.
2. Stored raw candidate-level features from H6/H7 deterministic variants.
3. One reranker axis at a time: Gemini Lite, Qwen3-Reranker, Gemma 26B-A4B if local latency is acceptable.
4. A held-out calibration split: train weights on 700 cases, validate on 150, report once on 150 test cases.

Do not use the same 100 cases both to invent and to claim the final metric.

## 1k Train/Test Follow-Up

The 5k run was deferred because the prepared public slice currently has 1,000 cases. I generated fresh 1,000-case per-case rankings for three deterministic rankers and ran a strict train/test split:

- train: first 900 common cases
- test: next 100 common cases
- no LLM/API calls
- no test labels used for training, except the oracle diagnostic

Generated local reports:

| Report | Rows | Notes |
| --- | ---: | --- |
| `.code-diver/reports/h8-train1k-h6-deterministic-1000.json` | 1,000 | H6.1 deterministic hybrid. |
| `.code-diver/reports/h8-train1k-h7-api-manifest-deterministic-1000.json` | 1,000 | H7 API-manifest deterministic hybrid. |
| `.code-diver/reports/h8-train1k-h7-query-expansion-deterministic-1000.json` | 1,000 | H7 query-expansion deterministic hybrid. |
| `.code-diver/reports/h8-reranker-ensemble-train900-test100-deterministic.json` | 100 test cases | H8 ensemble analysis. |

Command:

```bash
uv run python scripts/analyze_reranker_ensemble.py \
  --report h6=.code-diver/reports/h8-train1k-h6-deterministic-1000.json \
  --report h7_tiebreak=.code-diver/reports/h8-train1k-h7-api-manifest-deterministic-1000.json \
  --report h7_query_expansion=.code-diver/reports/h8-train1k-h7-query-expansion-deterministic-1000.json \
  --train-size 900 \
  --test-size 100 \
  --output .code-diver/reports/h8-reranker-ensemble-train900-test100-deterministic.json
```

Full 1,000-case single-run metrics:

| Run | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `h6` | 0.856 | 0.960 | 0.982 | 0.987 | 0.909 | 0.929 | 3145.7 |
| `h7_tiebreak` | 0.858 | 0.956 | 0.977 | 0.987 | 0.910 | 0.930 | 1609.7 |
| `h7_query_expansion` | 0.857 | 0.957 | 0.980 | 0.987 | 0.909 | 0.928 | 780.2 |

Held-out 100-case test metrics after training on the first 900:

| Hypothesis | Method | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `H8.0` | Best single ranker: `h7_query_expansion` | 0.940 | 0.980 | 0.980 | 1.000 | 0.959 | 0.969 | Baseline winner on this holdout. |
| `H8.1` | Plain RRF: `h6 + h7_tiebreak + h7_query_expansion` | 0.930 | 0.980 | 0.980 | 1.000 | 0.956 | 0.967 | Reject as default; no gain. |
| `H8.2` | Weighted RRF grid, trained on 900 | 0.920 | 0.980 | 0.980 | 1.000 | 0.949 | 0.962 | Reject; tuned weights overfit/demote top result. |
| `H8.3` | Logistic stacking meta-ranker, trained on 900 | 0.930 | 0.980 | 0.980 | 1.000 | 0.956 | 0.967 | Active only with more diverse rankers; deterministic-only stack does not beat best single. |
| `H8-ORACLE` | Best rank across all rankers using labels | 0.940 | 0.980 | 0.990 | 1.000 | not scored | not scored | Upper bound only, not deployable. |

Interpretation:

- On this held-out 100-case tail, the three deterministic rankers are too correlated. The best single ranker already reaches Hit@10 `1.000`, so there is almost no recall headroom.
- The trainable ensemble does not beat `h7_query_expansion` on Hit@1/MRR/nDCG.
- The earlier 100-case ensemble gain came from adding diverse agentic rankers. Without those extra ranker families, the meta-ranker mostly learns a reshuffle of the same signal.
- The next useful H8 test needs 1,000-case rankings from at least one genuinely different reranker family: Gemini Lite, Qwen3-Reranker cross-encoder, or a bounded local Gemma/Qwen listwise ranker. Deterministic variants alone are not enough.

## Hypotheses

### H8.1 - Plain RRF Reranker Ensemble

| Field | Value |
| --- | --- |
| Status | rejected as default |
| Search/ranking flow | Candidate file rankings from multiple rankers -> equal-weight Reciprocal Rank Fusion -> top 10 files. |
| 100-case result | Matched best H6.1 at Hit@1 `0.820`, Hit@10 `0.970`, nDCG `0.900`; adding agentic rankings degraded. |
| 900/100 result | Hit@1 `0.930`, Hit@10 `1.000`, nDCG `0.967`, below best single `h7_query_expansion`. |
| Decision | Keep as cheap diagnostic baseline only. |

### H8.2 - Weighted RRF Reranker Ensemble

| Field | Value |
| --- | --- |
| Status | rejected as default |
| Search/ranking flow | Candidate file rankings -> grid-search RRF weights on train split -> apply fixed weights to held-out test split. |
| 900/100 learned weights | `h6=0.25`, `h7_tiebreak=0.50`, `h7_query_expansion=0.25`. |
| 900/100 result | Hit@1 `0.920`, Hit@10 `1.000`, nDCG `0.962`. |
| Decision | Worse than both plain RRF and best single on this split. |

### H8.3 - Logistic Stacking Meta-Ranker

| Field | Value |
| --- | --- |
| Status | active research |
| Search/ranking flow | Candidate union -> rank features per candidate -> small logistic model -> final top 10 files. |
| Features | Per-ranker reciprocal rank, normalized rank, top-1 flag, agreement count, best-rank signal, average reciprocal-rank signal. |
| 100-case result | With deterministic + agentic saved outputs: Hit@1 `0.840`, Hit@10 `0.980`, nDCG `0.918`, beating best single Hit@1 `0.820`, Hit@10 `0.970`, nDCG `0.900`. |
| 900/100 deterministic-only result | Hit@1 `0.930`, Hit@10 `1.000`, nDCG `0.967`, below best single `h7_query_expansion` Hit@1 `0.940`, nDCG `0.969`. |
| Decision | Keep only if the input rankers are diverse. Deterministic-only stacking is not enough. |

### H8-ORACLE - Best-Rank Upper Bound

| Field | Value |
| --- | --- |
| Status | oracle / diagnostic only |
| Search/ranking flow | For each case, inspect all ranker outputs and select the best position of a known relevant file. |
| 100-case result | Across deterministic + agentic outputs: Hit@1 `0.940`, Hit@10 `0.990`. |
| 900/100 deterministic-only result | Hit@1 `0.940`, Hit@5 `0.990`, Hit@10 `1.000`. |
| Decision | Not deployable and not trainable, because it uses labels. Use only to estimate remaining headroom. |
