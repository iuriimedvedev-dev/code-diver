H-84v2: multi_query union_rerank feature notes.

This union_rerank mode fuses raw candidates from multiple query variants via RRF first, then runs CrossEncoder once on the fused pool, instead of running CrossEncoder inside each query variant separately (which is the older v1 behavior).

Factory wiring implemented in src/code_diver/strategies/retrieval_strategy_factory.py:
When multi_query is disabled, the base strategy is returned unchanged, meaning CrossEncoder wraps GraphFile directly.
When multi_query is enabled and union_rerank is false, this is v1 behavior, so MultiQuery wraps CrossEncoder which wraps GraphFile.
When multi_query is enabled and union_rerank is true, CrossEncoder wraps MultiQuery which wraps a CE-less GraphFile or Hybrid retriever, and the MultiQuery fusion_pool_size is set equal to the CrossEncoder candidate_limit value, which is 34 on the champion configuration.

Config change: added union_rerank boolean field defaulting to false in MultiQueryConfig, located in src/code_diver/config/multi_query_config.py.

Strategy change: added or confirmed fusion_pool_size parameter on MultiQueryRrfStrategy in src/code_diver/strategies/multi_query_rrf_strategy.py, which truncates the RRF fused pool to that size when provided.

New arm config file: configs/intellij/intellij-h84v2-union-rerank.yml, based on the champion config, with multi_query enabled true and union_rerank true, same collection as champion, same seed_score_parity and second_pass flags as champion.

Tests added or updated in tests/unit/test_multi_query_union_rerank.py, covering config defaults, all three factory branching modes, and fusion_pool_size truncation behavior.

End of notes.
