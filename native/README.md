# Native search core (`code_diver_search`)

Incremental Rust rewrite of **search scoring**, not CLI, eval, or embedding HTTP servers.

Python implementations stay in place (dual path). Champion config is unchanged.

## What exists today

- Inverted index ingest of **already-tokenized** documents (field weighting stays in Python for now).
- BM25 scores / top-k matching `HybridLexicalIndex.bm25_scores`.
- Scalar and batch `fuse_hybrid` matching `HybridCandidateScore.total` weights.
- Coverage fraction + lexical mix (`HybridCandidateScorer._coverage` / lexical formula).

## FFI (PyO3 module `code_diver_search`)

```python
from code_diver_search import InvertedIndex, fuse_hybrid_py, fuse_hybrid_batch_py

idx = InvertedIndex()
idx.ingest("doc-1", ["authorization", "token"])  # pre-tokenized
scores = idx.bm25_scores(["authorization", "token"], k1=1.2, b=0.75)
topk = idx.bm25_topk(["authorization"], k=10, k1=1.2, b=0.75)

total = fuse_hybrid_py(
    0.8, 0.5, 0.1, 0.0,
    vector_weight=0.5, lexical_weight=0.3, path_weight=0.2,
)

totals = fuse_hybrid_batch_py(
    [0.8, 0.2], [0.5, 0.9], [0.1, 0.3], [0.0, 0.4],
    [0.0, 0.2], [0.1, 0.5], [0.0, 0.2],
    vector_weight=0.5, lexical_weight=0.3, path_weight=0.2,
)
```

Planned (not implemented):

- `ingest_postings(...)` bulk load of Python `item_ids_by_term` / TFs.
- Graph-file **file-level** aggregation (full-catalog loop).

## Python sources this crate is porting from

| Piece | File |
| --- | --- |
| Inverted index + BM25 | `src/code_diver/strategies/hybrid_lexical_index.py` |
| Field coverage scores | `src/code_diver/strategies/hybrid_candidate_scorer.py` |
| Weighted sum | `src/code_diver/strategies/hybrid_candidate_score.py` |
| Hybrid scoring / RRF / file-vote | `src/code_diver/strategies/hybrid_retrieval_strategy.py` |
| Full-catalog file lexical seed loop | `src/code_diver/strategies/graph_file_retrieval_strategy.py` (`_seed_scores`, ~171–196) |

## Next port order

1. **File-level aggregation** — graph-file catalog loop + decayed neighbor propagate.
2. Symbol-match scorer (needs item metadata) if hot.
3. Wire dual-path behind a flag (do not flip champion until parity tests pass).

## Build

Root `pyproject.toml` stays **hatchling**. This crate is optional.

```bash
cd native/code_diver_search
# Rust unit tests (no Python)
cargo test --no-default-features

# Extension module (needs rustc + maturin)
pip install maturin
maturin develop --extras ""   # or: maturin build
```

If `rustc` or `maturin` is missing, the crate still lives here; install:

- https://rustup.rs
- `pip install maturin`

Then run `cargo test --no-default-features` and `maturin develop` from this directory.
