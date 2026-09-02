# H-84v2: pre-CE multi-query RRF (union then one CE)

## New flag
- `union_rerank: bool = False` added to `MultiQueryConfig` (src/code_diver/config/multi_query_config.py), `defaults.py`, and parsed in `config_loader.py` following the same pattern as `enabled`.

## Files changed
- src/code_diver/config/multi_query_config.py
- src/code_diver/config/defaults.py
- src/code_diver/config/config_loader.py
- src/code_diver/strategies/multi_query_rrf_strategy.py
- src/code_diver/strategies/retrieval_strategy_factory.py
- configs/intellij/intellij-h84v2-union-rerank.yml (new arm)
- tests/unit/test_multi_query_union_rerank.py (new tests)

## Wiring (RetrievalStrategyFactory.create())
- Case A — `multi_query.enabled=False`: bit-exact passthrough, unchanged, no new objects constructed.
- Case B — `enabled=True`, `union_rerank` false/absent: unchanged v1 behavior. Full pipeline (CE included when strategy is `graph_file_cross_encoder`) is built per variant, then the whole thing is wrapped in `MultiQueryRrfStrategy`. CE runs once per query variant (up to `max_variants` times), then RRF fuses already-reranked lists.
- Case C — `enabled=True`, `union_rerank=True`, strategy is `graph_file_cross_encoder`: new behavior. The inner `GraphFile(Hybrid(vector))` strategy is built via the new `_create_graph_file_base` helper (extracted from the existing `graph_file` / `graph_file_cross_encoder` construction code, no behavior change to those paths). That inner strategy is wrapped in `MultiQueryRrfStrategy` with `fusion_pool_size` set to the cross-encoder config's `candidate_limit`. That is wrapped in a single outer `CrossEncoderRerank`. CE now runs exactly once, over the fused candidate pool. If the strategy type is not `graph_file_cross_encoder`, union_rerank is a no-op and Case B behavior applies.

## MultiQueryRrfStrategy.fusion_pool_size
- New optional constructor parameter `fusion_pool_size: int | None = None`.
- When `None`: `search(query, limit)` behaves exactly as before (bit-exact), used by all existing callers/tests.
- When set: `effective_limit = max(limit, fusion_pool_size)` is used as the per-variant request size and the fused/returned result size, letting the outer CE wrapper receive a wide enough candidate pool to rerank down to the caller's real `limit`.

## Why this should not repeat v1's MRR collapse
H-84 v1 reranked each query variant's results independently with the cross-encoder, THEN fused the already-reranked lists via RRF. Independently-reranked, borderline results from multiple variants could get promoted by RRF fusion, diluting precision at the very top of the list — this is a plausible explanation for v1's MRR (0.3726→0.3266) and hit@1 (0.2308→0.1923) regressions despite a recall gain. H-84v2 instead fuses raw retrieval candidates from all variants FIRST (before any reranking) into one unified pool via RRF, then runs the cross-encoder exactly once over that pool. This mirrors how the single-query champion pipeline already behaves (one coherent CE pass over one candidate set), while still gaining the wider recall benefit of multi-query fan-out, avoiding the double-reranking / inconsistent-scoring dynamic suspected to cause v1's precision-at-top-rank regression.

## Latency expectation
~1.2–1.8x baseline latency, not 2.7x like v1. The expensive step (cross-encoder reranking) now runs once per query instead of once per query variant (previously up to `max_variants`=4 times). Remaining overhead vs. baseline comes from generating multiple query variants and running the cheaper retrieval stages (vector/hybrid/graph_file) multiple times before fusion — far cheaper than repeating full CE reranking multiple times.

## Arm config
`configs/intellij/intellij-h84v2-union-rerank.yml` — copy of `intellij-h66b-champion.yml` plus:
```yaml
multi_query:
  enabled: true
  union_rerank: true
  max_variants: 4
  rrf_k: 60
  original_query_weight: 2.0
  llm_rewrites_enabled: false
  parallel_variants: true
  max_variant_workers: 4
```
and `experiments.suite: h84v2-union-rerank`. Search-time only, same collection as champion.

## Test coverage
New file `tests/unit/test_multi_query_union_rerank.py` covers:
- Default OFF / enabled-without-union_rerank: factory wiring unchanged vs. today (CE inside each variant, `fusion_pool_size=None`).
- `union_rerank=True`: inner underlying of `MultiQueryRrfStrategy` does not include `CrossEncoderRerank`; outer strategy is `CrossEncoderRerank` wrapping `MultiQueryRrfStrategy`; `fusion_pool_size` equals the cross-encoder `candidate_limit`.
- `MultiQueryRrfStrategy.search` pool-size behavior: with `fusion_pool_size` set, per-variant requests and fused output use `effective_limit`; with it unset, behavior is bit-exact to before.
- `multi_query.enabled=False`: bit-exact passthrough.
- Champion yaml still loads with `multi_query` disabled and `union_rerank` defaulting to `False`.

## Evaluation status
Unit tests only. The live WHERE evaluation (GPU/index-backed) was intentionally NOT run, per task constraints. Recall/MRR/hit@1/latency numbers for this arm are pending a live WHERE-78 run.
