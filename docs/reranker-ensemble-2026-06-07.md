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
