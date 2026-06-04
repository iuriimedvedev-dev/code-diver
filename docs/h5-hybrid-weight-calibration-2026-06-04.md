# H5 Hybrid Weight Calibration

Date: 2026-06-04

## Why This Exists

H5 remains the default quality profile: file-first H3 candidate generation plus an LLM final ranker. The previous hybrid weights were manual engineering defaults. They were useful for experimentation, but they were not trained or calibrated.

This calibration pass keeps H5 as the default architecture and makes the deterministic candidate-generator weights falsifiable:

1. Build or reuse the H5 file-metadata index.
2. Collect candidate ranking features for a fixed dataset split.
3. Tune only the deterministic H3 hybrid weights on the train split.
4. Freeze the best profiles.
5. Evaluate them on a held-out validation split.
6. Run H5 LLM reranking only after candidate-generator weights are frozen.

## Primary Metrics

H5 is a file locator, so file-level metrics are primary:

| Metric | Why |
| --- | --- |
| `file_hit_rate@1` | Did the first deduplicated file hit the answer? |
| `file_hit_rate@3` / `file_hit_rate@5` | Useful for interactive search where the agent can inspect a short shortlist. |
| `file_hit_rate@10` | Candidate recall for final reranking and explanation. |
| `file_mrr@10` | Ranking quality across the top 10 files. |
| `file_recall@10` | Multi-file answer coverage. |
| `file_precision@R` | Cleanliness over the number of expected files. |

Item-level `precision@10` is secondary for H5 because the same file can appear as both `file_summary` and `file_manifest`. That metric is duplicate-sensitive and can overstate or understate user-visible file quality.

## Current Status

The current default H5 weights are still the manual profile in product config until a locked final eval confirms the calibrated candidate:

```yaml
vector_weight: 0.42
lexical_weight: 0.26
path_weight: 0.12
symbol_weight: 0.10
symbol_match_weight: 0.10
graph_weight: 0.0
file_vote_weight: 0.06
```

The calibration script is:

```bash
uv run python scripts/calibrate_hybrid_weights.py \
  --config configs/codesearchnet-mteb-python-h5-qwen-quality.yml \
  --train-size 700 \
  --validation-size 300 \
  --output .code-diver/reports/h5-hybrid-weight-calibration-codesearchnet-1000.json
```

The script disables tracing, uses the existing H5 index, collects H3 candidate features once, and then sweeps normalized weight profiles without additional LLM calls.

Full output:

```text
.code-diver/reports/h5-hybrid-weight-calibration-codesearchnet-1000.json
```

## Smoke Result

Smoke split: 80 train / 20 validation from `codesearchnet_python_1000.jsonl`, seed `17`.

| Profile | Validation file hit@1 | hit@3 | hit@5 | hit@10 | file MRR@10 | file precision@R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Manual H5 | 0.600 | 0.850 | 0.850 | 0.850 | 0.708 | 0.600 |
| Best trained on 80 cases | 0.600 | 0.850 | 0.850 | 0.850 | 0.708 | 0.600 |

The smoke run did not justify changing defaults. The full 700/300 run is the first result that should be used for weight decisions.

## 1000-Case Calibration Result

Dataset: `codesearchnet_python_1000.jsonl`

Split: 700 train / 300 validation, seed `17`.

Profiles tested: `1296`.

Runtime: `862.6s` total, including `576.5s` context collection.

| Profile | Validation file hit@1 | hit@3 | hit@5 | hit@10 | file MRR@10 | file recall@10 | file precision@R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Manual H5 | 0.837 | 0.937 | 0.947 | 0.960 | 0.888 | 0.960 | 0.837 |
| Best calibrated candidate | 0.843 | 0.940 | 0.953 | 0.960 | 0.893 | 0.960 | 0.843 |

Best calibrated candidate:

```yaml
vector_weight: 0.4318181818181818
lexical_weight: 0.20454545454545453
path_weight: 0.09090909090909091
symbol_weight: 0.045454545454545456
symbol_match_weight: 0.045454545454545456
graph_weight: 0.09090909090909091
file_vote_weight: 0.09090909090909091
```

Interpretation:

- Calibration produced a small validation improvement in head ranking: `+0.0067 file_hit@1`, `+0.0067 file_hit@5`, `+0.0049 file_mrr@10`.
- `file_hit@10` and `file_recall@10` did not improve; candidate coverage is unchanged.
- The best profiles form a flat plateau, not one sharp winner. Several nearby profiles tie on validation.
- The calibrated profile lowers lexical/path/symbol weights and introduces graph/file-vote mass. That is plausible, but it should be locked and retested before becoming product default.
- H5 LLM reranking should be evaluated next on manual vs calibrated candidate generation. The calibration itself used no LLM calls.

## Methodology Notes

- Tune deterministic `hybrid` candidate generation, not `hybrid_rerank`; otherwise LLM cost and model variance pollute the weight search.
- Report the manual baseline next to the best trained profile.
- Treat route-specific rewrites in `HybridQueryRouter` as part of the effective profile. Calibration should eventually learn route-specific weights, not one global profile only.
- Keep graph weight at zero unless validation shows it helps. The current default H5 graph artifact mostly contains summary/import edges and search expansion is disabled.
- Do not optimize against the final test split. If a profile is chosen from validation, run one final locked evaluation separately.
