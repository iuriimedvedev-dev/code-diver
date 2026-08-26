# Rust search-core: file propagate + dual-path

## Done
- rustc 1.98.0 / cargo 1.98.0 (PATH needs `~/.cargo/bin`)
- `cargo test --no-default-features`: **18 passed**
- maturin develop (venv 3.12): extension installed
- Ported file-level decayed neighbor propagate + adjacency expand
- Dual-path via `CODE_DIVER_NATIVE_SEARCH` default OFF; Python fallback

## Native now
- BM25 / InvertedIndex, fuse_hybrid(+batch), coverage, lexical_from_coverages
- propagate_file_scores, expand_adjacency (+ PyO3)

## Still Python
- Full-catalog `_seed_scores`, symbol-match scorer, bulk ingest_postings, HybridLexicalIndex dual-path BM25
- Champion YAML untouched

## Next
1. Catalog lexical seed loop
2. Symbol-match if hot
3. ingest_postings + BM25 dual-path
4. Parity harness before any champion flip
