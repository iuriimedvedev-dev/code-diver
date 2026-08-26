# Native search core (`code_diver_search`)

Incremental Rust rewrite of **search scoring**, not CLI, eval, or embedding HTTP servers.

Python implementations stay in place (dual path). Champion config is unchanged.

## What exists today

- Inverted index ingest of **already-tokenized** documents (field weighting stays in Python for now).
- BM25 scores / top-k matching `HybridLexicalIndex.bm25_scores`.
- Scalar and batch `fuse_hybrid` matching `HybridCandidateScore.total` weights.
- Coverage fraction + lexical mix (`HybridCandidateScorer._coverage` / lexical formula).
- **File-level decayed neighbor propagate**:
  - `propagate_file_scores` ↔ `GraphFileRetrievalStrategy._propagate` (`decay ** (depth+1)`, seed/neighbor/frontier limits).
  - `expand_adjacency` ↔ `FileGraphAdjacencyIndex.expand` (`decay ** depth`, `best_seen`, `min_score`).

## Dual path (default OFF)

Python glue: `src/code_diver/native_search.py`.

| Flag | Effect |
| --- | --- |
| unset / `0` / empty | **Python only** (production default; champion must stay here) |
| `CODE_DIVER_NATIVE_SEARCH=1` | Prefer native when the extension module imports; else silent Python fallback |

Wired call sites (still Python when flag off or module missing):

- `HybridCandidateScore.total` → `fuse_hybrid_py`
- `GraphFileRetrievalStrategy._propagate` → `propagate_file_scores_py`
- `FileGraphAdjacencyIndex.expand` → `expand_adjacency_py`

## FFI (PyO3 module `code_diver_search`)

```python
from code_diver_search import (
    InvertedIndex,
    fuse_hybrid_py,
    fuse_hybrid_batch_py,
    propagate_file_scores_py,
    expand_adjacency_py,
)

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

adjacency = {"a.py": [("b.py", 1.0), ("c.py", 0.5)]}
propagated = propagate_file_scores_py(
    adjacency, {"a.py": 1.0},
    depth=2, decay=0.5, seed_limit=10, neighbor_limit=10,
)
expanded = expand_adjacency_py(
    adjacency, {"a.py": 1.0},
    depth=1, decay=0.72, neighbor_limit=24, min_score=0.0,
)
```

Planned (not implemented):

- `ingest_postings(...)` bulk load of Python `item_ids_by_term` / TFs.
- Full-catalog lexical **seed** loop (`GraphFileRetrievalStrategy._seed_scores` O(n) scorer).

## Python sources this crate is porting from

| Piece | File |
| --- | --- |
| Inverted index + BM25 | `src/code_diver/strategies/hybrid_lexical_index.py` |
| Field coverage scores | `src/code_diver/strategies/hybrid_candidate_scorer.py` |
| Weighted sum | `src/code_diver/strategies/hybrid_candidate_score.py` |
| Hybrid scoring / RRF / file-vote | `src/code_diver/strategies/hybrid_retrieval_strategy.py` |
| Graph-file neighbor propagate | `src/code_diver/strategies/graph_file_retrieval_strategy.py` (`_propagate`) |
| File adjacency expand | `src/code_diver/strategies/file_graph_adjacency_index.py` (`expand`) |
| Full-catalog file lexical seed loop | `src/code_diver/strategies/graph_file_retrieval_strategy.py` (`_seed_scores`, ~171–196) |

## Next port order

1. **Full-catalog lexical seed loop** — `GraphFileRetrievalStrategy._seed_scores` (coverage/path/symbol over catalog; needs profiles or pre-tokenized fields).
2. Symbol-match scorer (needs item metadata) if hot.
3. Bulk `ingest_postings` + optional native BM25 dual-path on `HybridLexicalIndex` (when flag on).
4. Parity harness vs Python on IntelliJ-scale fixtures before any champion flip (champion stays Python).

## Build

Root `pyproject.toml` stays **hatchling**. This crate is optional.

```bash
cd native/code_diver_search
# Rust unit tests (no Python)
cargo test --no-default-features

# Extension module (needs rustc + maturin); PATH must include ~/.cargo/bin
pip install maturin
maturin develop --extras ""   # or: maturin build
```

If `rustc` or `maturin` is missing, the crate still lives here; install:

- https://rustup.rs
- `pip install maturin`

Then run `cargo test --no-default-features` and `maturin develop` from this directory.
