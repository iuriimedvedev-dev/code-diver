# 2026-09-01 — H-81 hybrid fusion width fix (arm implemented, not yet measured)

## What changed

Two gated flags, both default OFF (bit-exact current behaviour; full unit suite green):

1. `graph_file_search.fusion_pool_parity: bool = false`
   `GraphFileRetrievalStrategy._seed_scores` requested only `max(limit, seed_limit)` =
   `max(34, 140)` = 140 fused results from the base hybrid stage, so the hybrid stage's
   configured `candidate_limit`-wide (360) fused pool was trimmed to 140 before it ever
   reached graph-file fusion. With the flag on, the new `_seed_pool_limit` also honours the
   base strategy's `config.candidate_limit` (duck-typed, falls back cleanly when the base has
   no such attribute). Pool width is decided at this Python call-site, before any native
   (Rust) call — `seed_scores.rs` only handles the lexical lane, so no Rust change needed.

2. `hybrid_search.preserve_vector_kind_top: int = 0`
   `_preserve_vector_top` only rescues the single global vector rank-1 after the fused-rank
   trim, so a strong single-lane vector hit (FindInProjectManager, file_manifest lane
   rank 22) was still evicted from the 140 pool. New `_preserve_vector_kind_tops` step in
   `HybridRetrievalStrategy.rank_context` guarantees the top-K vector hits of every index
   kind a slot in the returned pool: preserved hits are appended at the pool floor score
   (membership only, never a better fused rank), displacing the weakest non-preserved tail
   entries.

## Arm config

`configs/intellij/intellij-h81-fusion-width.yml` — copy of `intellij-h66b-champion.yml`
(untouched) with `fusion_pool_parity: true` and `preserve_vector_kind_top: 32` (rank-22
eviction covered with headroom). Same collection, search-time only.

## Files

- `src/code_diver/config/graph_file_search_config.py`, `hybrid_search_config.py`,
  `config_loader.py` — flags + parsing (mirrors the `seed_score_parity` pattern)
- `src/code_diver/strategies/graph_file_retrieval_strategy.py` — `_seed_pool_limit`
- `src/code_diver/strategies/hybrid_retrieval_strategy.py` — `_preserve_vector_kind_tops`,
  `_vector_kind_tops`
- Tests: `tests/unit/test_graph_file_retrieval_strategy.py`,
  `test_hybrid_retrieval_strategy.py`, `test_config_loader.py`

## Expected effect / next steps

Recover the ~4 of 79 WHERE gold files that funnel instrumentation showed dying at the hybrid
fusion stage. Run the WHERE-79 eval on the H-81 arm vs the champion floor before considering
promotion. `pytest tests/unit`: 1353 passed, 1 pre-existing environmental failure
(`test_validate_eval_dataset` — `uv run` sync fails on the 404'd `vllm_metal` wheel URL),
unrelated to this change.
