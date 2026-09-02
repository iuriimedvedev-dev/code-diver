# H-84v2: pre-CE multi-query RRF (union then one CE)

## Implementation

- `MultiQueryConfig.union_rerank` defaults to `false` and is loaded from the `multi_query` YAML mapping.
- Disabled multi-query returns the factory's base strategy unchanged.
- Enabled multi-query with `union_rerank=false` preserves H-84 v1: the complete pipeline, including CE, runs per variant and the ranked lists are fused.
- Enabled multi-query with `union_rerank=true` applies only to `graph_file_cross_encoder`: raw `GraphFile(Hybrid(vector))` results are fused, then one outer cross-encoder reranks the pool.
- Other supported strategies keep the v1 wrapper behavior; unknown strategy IDs retain the factory's existing `ValueError` behavior.

## Fusion Pool

`MultiQueryRrfStrategy.fusion_pool_size` is optional and defaults to `None` for existing behavior. When configured, each variant is requested with `max(limit, fusion_pool_size)` and the fused result is truncated to that same effective size. H-84v2 sets it to the cross-encoder `candidate_limit` so the outer reranker receives a wide candidate pool.

## Rationale

H-84 v1 reranked each variant independently before fusing, allowing borderline results to be promoted by RRF and diluting top-rank precision. H-84v2 fuses raw retrieval candidates first and runs CE once, matching the champion's single coherent CE pass while retaining multi-query recall. Expected latency is approximately 1.2-1.8x baseline rather than up to 2.7x because CE runs once per query.

## Files

- `src/code_diver/config/multi_query_config.py`
- `src/code_diver/settings/defaults.py`
- `src/code_diver/config/config_loader.py`
- `src/code_diver/strategies/multi_query_rrf_strategy.py`
- `src/code_diver/strategies/retrieval_strategy_factory.py`
- `configs/intellij/intellij-h84v2-union-rerank.yml`
- `tests/unit/test_multi_query_union_rerank.py`

## Arm

`intellij-h84v2-union-rerank.yml` follows the H-66b champion configuration and uses the same collection, with deterministic multi-query enabled and suite `h84v2-union-rerank`.

## Validation

Unit tests were not run because the task explicitly prohibits pytest and live evaluation commands.
