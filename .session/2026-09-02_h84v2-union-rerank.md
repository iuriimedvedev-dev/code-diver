# H-84v2: multi_query.union_rerank

## What it does
Instead of running CrossEncoder reranking inside each query variant (v1 behavior), union_rerank fuses raw candidates from multiple query variants via RRF first, then runs CrossEncoder once on the fused/unioned pool.

## Factory wiring
File: src/code_diver/strategies/retrieval_strategy_factory.py
- multi_query disabled -> base strategy unchanged: CrossEncoder wraps GraphFile
- multi_query enabled, union_rerank false (v1) -> MultiQuery wraps (CrossEncoder wraps GraphFile)
- multi_query enabled, union_rerank true -> CrossEncoder wraps (MultiQuery wraps CE-less GraphFile/Hybrid), with MultiQuery fusion_pool_size set equal to CrossEncoder candidate_limit (34 on champion)

## Config
New field MultiQueryConfig.union_rerank (boolean, default False) in src/code_diver/config/multi_query_config.py, defaulting to False when absent from yaml.

## MultiQueryRrfStrategy
New/updated fusion_pool_size parameter on MultiQueryRrfStrategy in src/code_diver/strategies/multi_query_rrf_strategy.py, which truncates the RRF-fused pool to that size when provided, falling back to prior default behavior otherwise.

## New arm config
configs/intellij/intellij-h84v2-union-rerank.yml, based on champion, with multi_query.enabled true and multi_query.union_rerank true, same collection intellij_h66b_budget_qwen, same seed_score_parity and second_pass flags as champion.

## Tests
tests/unit/test_multi_query_union_rerank.py covers config defaults, factory branching for all three modes, and fusion_pool_size truncation behavior.
