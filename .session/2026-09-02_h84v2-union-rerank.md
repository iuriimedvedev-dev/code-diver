# 2026-09-02 — H-84 v2 union rerank

## Configuration

- `MultiQueryConfig` declares `union_rerank: bool = False` in `src/code_diver/config/multi_query_config.py`.
- The requested `src/code_diver/config/defaults.py` does not exist in this checkout. The actual defaults definition is `src/code_diver/settings/defaults.py`, where `MULTI_QUERY_UNION_RERANK = False`.
- `src/code_diver/config/config_loader.py` maps `multi_query.union_rerank` with `Defaults.MULTI_QUERY_UNION_RERANK` as its fallback.

## Files Touched

- Config files: `src/code_diver/config/multi_query_config.py`, `src/code_diver/settings/defaults.py`, and `src/code_diver/config/config_loader.py`.
- `src/code_diver/strategies/retrieval_strategy_factory.py`.
- `src/code_diver/strategies/multi_query_rrf_strategy.py`.
- New arm: `configs/intellij/intellij-h84v2-union-rerank.yml`.
- New tests: `tests/unit/test_multi_query_union_rerank.py`.

## Factory Cases

`RetrievalStrategyFactory.create` has three relevant cases:

- **A, multi-query disabled:** returns `_create_base(...)` directly. This is a bit-exact passthrough with no `MultiQueryRrfStrategy` wrapper.
- **B, enabled with `union_rerank` false or absent:** v1 remains unchanged. The factory wraps the base strategy in `MultiQueryRrfStrategy`; for `graph_file_cross_encoder`, the cross-encoder remains inside that wrapper and runs per variant before RRF.
- **C, enabled with `union_rerank` true:** for `graph_file_cross_encoder`, the factory uses the inner `GraphFile(Hybrid(vector))` base from `_create_graph_file_base`, wraps it in `MultiQueryRrfStrategy` with `fusion_pool_size` equal to the cross-encoder `candidate_limit`, then applies one outer `CrossEncoderRerank`.

## RRF Pooling

- `MultiQueryRrfStrategy` accepts `fusion_pool_size: int | None = None`.
- `None` preserves the old behavior bit-exactly: per-variant searches and fused output use the requested `limit`.
- When set, `effective_limit = max(limit, fusion_pool_size)` drives per-variant searches and the fused output size. This lets v2 form a sufficiently wide raw union before the outer cross-encoder cut.

## Why V2

- v1 performs CE-then-RRF: every query variant runs the full cross-encoder pipeline, and the already-reranked variant lists are fused. Variant-local CE decisions can discard candidates before they can accumulate support across variants, causing the observed MRR collapse.
- v2 performs raw retrieval RRF first and one CE pass over the union. Candidates remain available to accumulate rank support across variants, while the final ordering is made by one cross-encoder pass. This keeps the result formation coherent with the single-query champion's graph-file retrieval plus CE ordering instead of fusing separately reranked variant decisions.

## Latency

- The expected v2 latency is approximately `1.2-1.8x` baseline, versus approximately `2.7x` for v1.
- V2 invokes the cross-encoder once rather than up to `max_variants=4` times. Retrieval and variant-generation overhead is cheaper than repeating the full CE stage, and variant retrieval remains parallel when configured.

## Arm

`configs/intellij/intellij-h84v2-union-rerank.yml` copies the champion and sets:

- `multi_query.enabled=true`
- `multi_query.union_rerank=true`
- `multi_query.max_variants=4`
- `multi_query.rrf_k=60`
- `multi_query.original_query_weight=2.0`
- `multi_query.llm_rewrites_enabled=false`
- `multi_query.parallel_variants=true`
- `multi_query.max_variant_workers=4`
- `experiments.suite=h84v2-union-rerank`

## Unit Tests

`tests/unit/test_multi_query_union_rerank.py` covers:

- `test_multi_query_config_union_rerank_defaults_to_false`: the config default is disabled.
- `test_factory_keeps_cross_encoder_inside_multi_query_by_default`: enabled v1 keeps CE inside the multi-query wrapper.
- `test_factory_union_rerank_wraps_multi_query_before_one_cross_encoder`: v2 places one CE outside the RRF wrapper and uses its candidate limit as the fusion pool.
- `test_rrf_overfetches_each_variant_and_respects_effective_limit`: configured fusion width controls variant retrieval and output width.
- `test_rrf_without_fusion_pool_requests_exact_limit`: absent fusion width preserves exact requested-limit behavior.
- `test_factory_disabled_multi_query_is_bit_exact_passthrough`: disabled multi-query returns the base strategy unchanged.

## Evaluation Status

Live WHERE evaluation was **not** run. Validation was limited to unit tests; no GPU or index evaluation was performed, consistent with the constraints.
