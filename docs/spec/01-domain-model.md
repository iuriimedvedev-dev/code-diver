# 01 — Domain Model

Location: `src/code_diver/domain/`, `src/code_diver/graph/`

The domain layer is the vocabulary every other subsystem speaks. It is intentionally
free of I/O, providers, and config.

## CodeItem — the unit of indexing

`domain/code_item.py`

The atomic indexed snippet. One repository becomes many `CodeItem`s.

| Field | Meaning |
|-------|---------|
| `id` | Stable identity (path + line range + kind) |
| `path` | Repo-relative source path |
| `title` | Human label (symbol name / file name) |
| `content` | Source text of the snippet |
| `start_line` / `end_line` | 1-based inclusive line range |
| `metadata` | Kind, symbols, imports (see `CodeItemMetadata`) |

**Contract**
- `to_embedding_text()` formats the item for an embedding model.
- `to_json()` / `from_json()` round-trip losslessly (used by JSON store + traces).
- An item belongs to exactly one **index kind** (below).

### Index kinds — `code_item_index_kind.py`

`chunk` · `symbol` · `file_summary`. A resolver
(`code_item_index_kind_resolver.py`) maps metadata → kind. Kinds carry different
weights in hybrid scoring (see [04](./04-hybrid-search.md)).

- **chunk** — fixed-line window of a file.
- **symbol** — one function/class extracted by `CodeSymbolExtractor`.
- **file_summary** — per-file synthetic item (imports + leading symbols), built by
  `FileSummaryItemBuilder`.

## CodeSymbol — `code_symbol.py`

Extracted definition: `name`, `kind` (function/class/method), `path`, line location.
Produced by `services/code_symbol_extractor.py` for Python/TypeScript/others.

## SearchResult — `search_result.py`

`CodeItem` + `score: float`. The currency returned by every `RetrievalStrategy`.

**Contract (intended)**
- `score` is comparable *within one query's result list* (for ranking).
- ⚠️ Divergence: scores are **not** comparable across queries or across strategy
  configs — min-max normalization and non-unity weight sums break cross-query
  semantics (⚠️ R-4, R-5). Treat `score` as ordinal only.

## EvalCase / EvalResult — `eval_case.py`, `eval_result.py`

- `EvalCase`: `query` + expected retrieval targets + bucket label.
- `EvalResult`: `hit`, `reciprocal_rank`, `precision`, `recall`, `ndcg`,
  `average_precision`, `bucket`. Computed by `EvaluationService` + `math_utils.py`.

**Bucket taxonomy** (`eval_case_bucket_classifier.py`): `semantic`, `path`, `symbol`,
`workflow`, `exact`. Buckets drive both routing (which weights/edges to use) and
per-category metric reporting.

## CodeGraph — `graph/code_graph.py`

Items + typed edges. Enables graph-expansion retrieval.

| Component | File |
|-----------|------|
| `CodeGraph` (items dict + edges, `neighbors(id)`) | `graph/code_graph.py` |
| `GraphEdge` (source, target, kind, weight) | `graph/graph_edge.py` |
| Builder (orchestrates edge construction) | `graph/code_graph_builder.py` |
| Containment edges (chunk→symbol, class→method) | `graph/graph_containment_builder.py` |
| Python call edges (AST) | `graph/python_ast_call_graph_builder.py` |
| Persistence | `graph/code_graph_store.py` |

**Edge kinds** (`settings/edge_kind.py`): `same_file_next`, `summarizes`, `imports`,
`references`, `contains`, `calls`.

**Contract**
- `neighbors(item_id)` is bidirectional.
- Edges carry a weight consumed by `GraphCandidateExpander` with per-hop decay.
- ⚠️ Divergence: call/reference edges are **Python-centric**; other languages get only
  containment + same_file_next coverage. Graph retrieval quality is language-skewed.

## Invariants the domain assumes (and where they leak)

1. **Stable ids** — re-indexing the same file must produce the same item ids. Holds for
   `scanner` mode; ⚠️ AI/orchestrated modes can vary line selections run-to-run,
   weakening reproducibility.
2. **Lossless JSON** — required for the JSON store and trace replay. Holds.
3. **One kind per item** — relied on by kind-weighted scoring. Holds.
