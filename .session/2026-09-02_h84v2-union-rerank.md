# H-84v2: union rerank

## Summary

`union_rerank` changes multi-query retrieval from reranking each variant separately to
fusing raw retrieval candidates first, then running one cross-encoder over the union.
The fusion pool is widened to the cross-encoder `candidate_limit`.

## Factory Wiring

- Multi-query disabled: unchanged base strategy.
- Enabled + `union_rerank=false`: `MultiQuery` wraps `CE` wraps `GraphFile`.
- Enabled + `union_rerank=true`: `CrossEncoder` wraps `MultiQuery` wraps CE-less `GraphFile`, with `fusion_pool_size = CE candidate_limit`.

## Changes

- Added `MultiQueryConfig.union_rerank`.
- Added `configs/intellij/intellij-h84v2-union-rerank.yml` arm.
- Added or updated `tests/unit/test_multi_query_union_rerank.py`.

## Validation

Unit tests and live evaluation were not run.
