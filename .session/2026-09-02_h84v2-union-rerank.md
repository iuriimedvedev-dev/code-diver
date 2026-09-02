---
# H-84v2: multi_query.union_rerank

## Summary
union_rerank fuses raw candidates from multiple query variants via RRF first, then runs CrossEncoder once on the fused pool, instead of running CrossEncoder inside each query variant (v1 behavior).

## Factory wiring (src/code_diver/strategies/retrieval_strategy_factory.py)
1. multi_query disabled -> base strategy unchanged: CrossEncoder wraps GraphFile
2. multi_query enabled, union_rerank false (v1) -> MultiQuery wraps (CrossEncoder wraps GraphFile)
3. multi_query enabled, union_rerank true -> CrossEncoder wraps (MultiQuery wraps CE-less GraphFile), fusion_pool_size = CE candidate_limit (34 on champion)

## Config
`MultiQueryConfig.union_rerank: bool = False` added in `src/code_diver/config/multi_query_config.py`.

## MultiQueryRrfStrategy
`fusion_pool_size` parameter honored in `src/code_diver/strategies/multi_query_rrf_strategy.py`.

## New arm
`configs/intellij/intellij-h84v2-union-rerank.yml` based on champion, multi_query.enabled=true, union_rerank=true, same collection/seed_score_parity/second_pass flags as champion.

## Tests
`tests/unit/test_multi_query_union_rerank.py` added/updated.
---
