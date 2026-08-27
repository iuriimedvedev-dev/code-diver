# Rust seed loop port

## Done
- `native/code_diver_search/src/seed_scores.rs` — `seed_coverages()` function: coverage/path/symbol scoring over all catalog items, zero-score filter, sort by (lexical desc, path desc, symbol desc, path asc), top-N truncation
- `seed_coverages_py` PyO3 binding in `lib.rs` — accepts `{item_id: {"title": [str], "path": [str], "content": [str], "metadata": [str]}}` profiles
- `try_seed_coverages` bridge in `native_search.py` — converts HybridItemProfile frozensets to lists for PyO3
- `_try_native_seed_coverages` method on `GraphFileRetrievalStrategy` — dual-path in `_seed_scores`
- 11 Rust unit tests (empty, match, no-match, sorting, limit, symbol_match)
- `native/README.md` — seed loop marked done, next: parity harness + symbol-match scorer

## Verified
- `cargo test --no-default-features`: 31/31 passed
- `pytest tests/`: 1186 passed, 3 skipped, 4 pre-existing failures (unrelated symbols-first tests)
- Smoke: native seed coverages returns correct scores, doc1 > doc2

## Next
- Parity harness vs Python on IntelliJ-scale fixtures before champion flip
- Symbol-match scorer (item metadata, if hot)