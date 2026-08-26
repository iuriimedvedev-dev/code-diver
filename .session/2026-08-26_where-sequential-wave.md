# 2026-08-26 sequential WHERE wave

## Keep
- Best index: H52 collection `intellij_h52_summary_head_first_qwen` (do not overwrite H46).
- Champion yaml still `intellij-h46-preserve-top.yml` — not flipped.
- Original WHERE-79 unchanged. Holdout is separate.

## WHERE-79 (n=79) vs jbcontext 0.685

| arm | recall@10 | MRR@10 |
|---|---|---|
| H46 | 0.503 | 0.285 |
| H52 | 0.537 | 0.312 |
| H52 + listwise gpt-4o-mini | 0.585 | 0.260 |
| jbcontext | 0.685 | ~0.347 |

Gold-in-pool@20 H52: 56/79.

## 1065
H52 file_recall@10 0.8365 vs H46 0.8311. Symbol/where up; config slightly down (0.790 vs 0.797). Path tied.

## Killed
- H-55 CE file-head: 0.243 / 0.104
- H-54 skip manifest vector: 0.496 / 0.257
- H-58 prose fusion router: 0.521 / 0.294

## Dataset
- `datasets/intellij_eval_where_holdout.jsonl` n=36, gold on disk
- H52 holdout recall@10 0.722 (different slice; do not mix with 79)
- 1 stale original: `where-editor-caret`

## Next
- Representation still the bottleneck (pool oracle ~0.66). Do not promote listwise (MRR regression).
- Do not flip champion until mechanical config regression is understood.
- H-57 query-time blurbs or extra purpose kind (H-59) next for remaining ~0.10 vs jbcontext.
