# H-84v2: multi_query.union_rerank

`union_rerank` fuses raw candidates from multiple query variants via RRF before running CrossEncoder once, unlike v1 per-variant reranking.

## Factory nesting

In `src/code_diver/strategies/retrieval_strategy_factory.py`, the factory handles three modes: disabled multi-query uses the existing strategy; enabled multi-query with `union_rerank: false` uses per-variant reranking; enabled multi-query with `union_rerank: true` uses union reranking. In the enabled-true branch, `fusion_pool_size` equals the CrossEncoder `candidate_limit`, which is 34 on champion.

## Configuration

`src/code_diver/config/multi_query_config.py` defines `MultiQueryConfig.union_rerank: bool = False`; the default is false when the field is absent from yaml.

## RRF strategy

`src/code_diver/strategies/multi_query_rrf_strategy.py` adds `fusion_pool_size` to `MultiQueryRrfStrategy`, truncating the fused RRF pool when provided.

## Arm config

`configs/intellij/intellij-h84v2-union-rerank.yml` is based on champion with `enabled` and `union_rerank` true, the same collection, `seed_score_parity`, and `second_pass_*` flags.

## Tests

`tests/unit/test_multi_query_union_rerank.py` covers defaults, all three factory branches, and truncation.
