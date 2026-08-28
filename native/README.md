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
- **Full-catalog lexical seed loop** — `seed_coverages` ↔ `GraphFileRetrievalStrategy._seed_scores` (coverage/path/symbol over all catalog items, filter, sort, top-N).
- **Vector math + batch cosine similarity** — `normalize`/`dot`/`search_flat`/`search_flat_f64` - L2 normalization, dot product, and batch cosine similarity over flat arrays. Replaces `math_utils.py` and `JsonVectorStore._search_items` (the real latency bottleneck).

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
- `HybridLexicalIndex.bm25_scores` → `bm25_scores_from_data_py` (avoids rebuilding InvertedIndex)
- `GraphFileRetrievalStrategy._seed_scores` → `seed_coverages_py` (full-catalog lexical seed loop)

## FFI (PyO3 module `code_diver_search`)

```python
from code_diver_search import (
    InvertedIndex,
    bm25_scores_from_data_py,
    seed_coverages_py,
    fuse_hybrid_py,
    fuse_hybrid_batch_py,
    propagate_file_scores_py,
    expand_adjacency_py,
    normalize_py,
    dot_py,
    search_flat_py,
    search_flat_f64_py,
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

# Vector math
norm = normalize_py([3.0, 4.0])           # [0.6, 0.8]
d = dot_py([1.0, 0.0], [0.0, 1.0])       # 0.0
results = search_flat_f64_py(
    [1.0, 0.0],                           # normalized query
    [1.0, 0.0, 0.0, 1.0],                # flat vectors (2 × 2D)
    [(0, 2), (2, 4)],                     # offsets
    10,                                   # limit
)  # [(0, 1.0), (1, 0.0)]
```

Planned (not implemented):

_(none — all planned ports are done)_

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
| Vector math (dot, normalize, batch cosine) | `src/code_diver/math_utils.py`, `src/code_diver/store/json_vector_store.py` (`_search_items`) |

## Next port order

1. Parity harness vs Python on IntelliJ-scale fixtures before any champion flip (champion stays Python).
2. Symbol-match scorer (needs item metadata) if hot.

**Done:** BM25 dual-path (`HybridLexicalIndex.bm25_scores` → `bm25_scores_from_data_py`).

**Done:** Full-catalog lexical seed loop (`GraphFileRetrievalStrategy._seed_scores` → `seed_coverages_py`).

**Done:** Vector math + batch cosine similarity (`math_utils.py` dot/normalize + `JsonVectorStore._search_items`).

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
