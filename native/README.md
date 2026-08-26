# Native search core (`code_diver_search`)

Incremental Rust rewrite of **search scoring**, not CLI, eval, or embedding HTTP servers.

Python implementations stay in place (dual path). Champion config is unchanged.

## What exists today

- Inverted index ingest of **already-tokenized** documents (field weighting stays in Python for now).
- BM25 scores / top-k matching `HybridLexicalIndex.bm25_scores`.
- Stub `fuse_hybrid` matching `HybridCandidateScore.total` weights.

## FFI (PyO3 module `code_diver_search`)

```python
from code_diver_search import InvertedIndex, fuse_hybrid_py

idx = InvertedIndex()
idx.ingest("doc-1", ["authorization", "token"])  # pre-tokenized
scores = idx.bm25_scores(["authorization", "token"], k1=1.2, b=0.75)
topk = idx.bm25_topk(["authorization"], k=10, k1=1.2, b=0.75)

total = fuse_hybrid_py(
    0.8, 0.5, 0.1, 0.0,
    vector_weight=0.5, lexical_weight=0.3, path_weight=0.2,
)
```

Planned (not implemented):

- `ingest_postings(...)` bulk load of Python `item_ids_by_term` / TFs.
- Hybrid field fusion over candidate batches (vector/lexical/path/symbol).
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

1. **BM25** (this crate) — ingest + score + top-k.
2. **Batch hybrid fusion** — `HybridCandidateScore.total` over arrays of field scores.
3. **Coverage scorer** — title/content/path/symbol term sets (from `HybridCandidateScorer`).
4. **File-level aggregation** — graph-file catalog loop + decayed neighbor propagate.
5. Wire dual-path behind a flag (do not flip champion until parity tests pass).

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
