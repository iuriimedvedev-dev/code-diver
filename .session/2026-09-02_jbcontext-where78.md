# Session: jbcontext Evaluation on WHERE-78 (2026-09-02)

## Execution Detail
- **Command**: python3 scripts/compare_jbcontext.py --dataset datasets/intellij_eval_where_only.jsonl --project-path /Users/iurii.medvedev/Work/intellij-community --raw-limit 40 --file-limit 10 --timeout-s 60 --out .code-diver/reports/jbcontext-where78.json
- **jbcontext version**: 0.9.11 (build 682, commit 8e433fe718, channel stable)
- **Snapshot/Revision used**: `141b8266cbc7` (detected via manual search sanity check; status also showed newer `8491c9258320` available).
- **Target revision mismatch**: Evaluation performed on `141b8266cbc7`; champion checkout was `4756d30e`. Indexing for `4756d30e` was skipped per instructions as it was not present and full indexing is slow.

## Metrics Summary (78 queries)
| Metric | Value |
| :--- | :--- |
| File Recall @ 10 | 0.7370 |
| File MRR @ 10 | 0.3499 |
| File Hit Rate @ 1 | 0.1923 |
| File Hit Rate @ 10 | 0.7821 |
| NDCG @ 10 | 0.4341 |
| MAP @ 10 | 0.3304 |
| Duration Mean | 1892 ms |
| Duration P95 | 2801 ms |

## Caveats
- Sequential run (no reranker).
- Revision mismatch: `141b8266cbc7` used instead of `4756d30e`.
- All 78 cases processed successfully with no search failures.
- Unique file counts in results confirmed valid (non-zero).
