# Rerank Ranking Analysis - 2026-06-01

Dataset: `datasets/protogen_eval_100.jsonl`, 100 informal code-navigation cases.

Main run:

```text
uv run code-diver --config configs/protogen-legacy/protogen-ollama-qdrant.yml experiment \
  --hypothesis hybrid_candidates_llm_rerank \
  --hypothesis hybrid_rerank_top20_compact \
  --hypothesis hybrid_rerank_file_first \
  --hypothesis hybrid_rerank_base_prior \
  --hypothesis hybrid_rerank_precision \
  --hypothesis hybrid_rerank_preserve_top
```

Run id: `427eff134985458fa5bd38f4bc3433d1`.

Deterministic control run:

```text
uv run code-diver --config configs/protogen-legacy/protogen-ollama-qdrant.yml experiment \
  --hypothesis vector_qdrant \
  --hypothesis hybrid_candidates_no_llm \
  --hypothesis hybrid_candidates_modern_graphrag
```

Run id: `031b9322144947d895d0faa220fcbbcc`.

## Root Cause

The first issue was measurement, not model ranking.

`EvaluationService` computed `hit_rate@1` and `hit_rate@3` from retrieved item ids only. Chunk ids look like `src/file.py#hash`, but symbol ids look like `src/file.py::Class#hash`. Expected values in the dataset are usually file paths, so symbols were incorrectly counted as misses for `hit@1/@3` even when their `path` was exactly the expected file.

Fix: `_matches_path_or_id` now accepts `expected + "::"` in addition to `expected + "#"`.

After the fix, the baseline bounded reranker is not `hit@1=0.27`; it is `hit@1=0.70`.

## Candidate Diagnostics

For the corrected `hybrid_candidates_llm_rerank` baseline:

| Diagnostic | Value |
| --- | ---: |
| Cases | 100 |
| Expected target present in top-40 candidates | 94 |
| Expected target absent from top-40 candidates | 6 |
| Candidate present but not selected by model | 1 |
| First relevant candidate already rank 1 before LLM | 62 |
| Mean first relevant candidate rank before LLM | 2.64 |
| Mean relevant rank inside model-selected output | 1.51 |

Interpretation: first-stage candidate generation is already strong. The remaining quality issue is not broad recall. It is top-rank ordering among related files/symbols, plus 6 true candidate misses.

## Corrected Baselines

| Hypothesis | Hit@10 | MRR@10 | Hit@1 | Hit@3 | Precision@10 | Recall@10 | File MRR@10 | nDCG@10 | MAP@10 | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.880 | 0.720 | 0.640 | 0.780 | 0.411 | 0.850 | 0.731 | 0.679 | 0.612 | 31ms |
| `hybrid_candidates_no_llm` | 0.890 | 0.721 | 0.630 | 0.780 | 0.452 | 0.855 | 0.741 | 0.683 | 0.616 | 134ms |
| `hybrid_candidates_modern_graphrag` | 0.900 | 0.718 | 0.620 | 0.810 | 0.452 | 0.875 | 0.737 | 0.682 | 0.613 | 139ms |
| `hybrid_candidates_llm_rerank` | 0.930 | 0.785 | 0.700 | 0.870 | 0.534 | 0.920 | 0.797 | 0.735 | 0.673 | 4.58s |

The LLM reranker is a real quality improvement over deterministic retrieval: `+0.06 hit@1` over vector, `+0.05 hit@10`, `+0.065 MRR`, and `+0.061 MAP`. The downside is API latency and token cost.

## Five Tested Ranking Hypotheses

| Hypothesis | Change | Hit@10 | MRR@10 | Hit@1 | Hit@3 | File MRR@10 | nDCG@10 | MAP@10 | Tokens | Cost | Mean model latency | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `hybrid_rerank_top20_compact` | 20 candidates, 450-char previews, no reasons | 0.910 | 0.788 | 0.700 | 0.860 | 0.798 | 0.734 | 0.675 | 505,970 | $0.850 | 2.38s | Keep as low-cost mode. |
| `hybrid_rerank_file_first` | Prompt ranks owning files before symbols/chunks | 0.930 | 0.809 | 0.730 | 0.880 | 0.818 | 0.752 | 0.694 | 1,199,151 | $2.079 | 4.07s | Best quality; promote. |
| `hybrid_rerank_base_prior` | Treat deterministic rank as strong prior | 0.930 | 0.802 | 0.720 | 0.870 | 0.808 | 0.746 | 0.687 | 1,200,406 | $2.084 | 4.19s | Safe, but below file-first. |
| `hybrid_rerank_precision` | Prompt optimizes first result specificity | 0.930 | 0.802 | 0.710 | 0.870 | 0.808 | 0.744 | 0.683 | 1,188,759 | $2.008 | 3.82s | Small gain; not enough. |
| `hybrid_rerank_preserve_top` | Pin top hybrid result when score gap >= 0.08 | 0.930 | 0.755 | 0.640 | 0.870 | 0.763 | 0.715 | 0.648 | 1,196,604 | $2.066 | 4.16s | Reject. |

## Case-Level Movement

Compared to corrected `hybrid_candidates_llm_rerank`:

| Hypothesis | Hit@1 wins | Hit@1 losses | Pattern |
| --- | ---: | ---: | --- |
| `top20_compact` | 7 | 7 | Same top-1 quality, lower recall and much lower cost. |
| `file_first` | 5 | 2 | Best net movement; fixes ownership confusions with limited regressions. |
| `base_prior` | 2 | 0 | Conservative and safe, but smaller total gain. |
| `precision` | 3 | 2 | Prompt wording helps a little but is noisy. |
| `preserve_top` | 1 | 7 | Simple score-gap pinning preserves bad deterministic tops too often. |

Notable `file_first` wins: `where-agent-runtime`, `where-eval-repository`, `where-mcp-config`, `where-monitor-api`, `where-schema-generator`.

Notable `file_first` losses: `where-codegen-prompts`, `where-platform-tools`.

## Conclusions

1. The scary `hit@1=0.27` was a metrics bug. The corrected bounded reranker is `hit@1=0.70`.
2. Candidate generation is not the main bottleneck: 94/100 expected targets are already present in top 40.
3. `file_first` is the best tested quality profile: `hit@1=0.73`, `MRR=0.809`, `MAP=0.694`.
4. `top20_compact` is the best cost profile: 58% fewer tokens and about 45% lower model latency, with `hit@1` unchanged but `hit@10` down by 0.02.
5. Naive deterministic top preservation is harmful. We need a smarter confidence gate, not a hard score-margin rule.

## Next Actions

- Make `file_first` the default high-quality rerank mode. Implemented in `Defaults.LLM_RERANK_MODE` and the protogen config-level `llm_rerank` block.
- Keep `top20_compact` as a low-cost/fast mode.
- Add real file-level grouping before the LLM call: first rank files, then rank candidate items inside chosen files.
- Add adaptive candidate count: use compact top-20 when deterministic agreement is high, top-40 when query/candidate signals disagree.
- Investigate the 6 cases where the expected target is absent from top-40; those require candidate generation/index improvements, not rerank prompt changes.
