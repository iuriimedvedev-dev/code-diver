# 05 — Code Graph

Optional structural layer linking `CodeItem`s with typed edges, enabling
graph-expansion retrieval (GraphRAG).

Files: `graph/*`, `strategies/graph_candidate_expander.py`,
`strategies/graph_expansion_profile_factory.py`, `services/graph_indexing_service.py`.
Config: `config/graph_config.py`.

## Build — `graph/code_graph_builder.py`

Builds a `CodeGraph` from the indexed items:

| Edge kind | Builder | Meaning |
|-----------|---------|---------|
| `same_file_next` | builder | Sequential chunks in one file |
| `contains` | `graph_containment_builder.py` | chunk→symbol, class→method (AST containment) |
| `summarizes` | builder | file_summary → its file's items |
| `imports` | builder | Module import relationships |
| `references` | builder | Symbol references |
| `calls` | `python_ast_call_graph_builder.py` | Python function call edges (AST) |

**Contract**: edges are typed and weighted; `neighbors()` is bidirectional;
graph build never blocks vector indexing (toggled by `graph.enabled`).

⚠️ Divergence: `calls` and `references` are derived from **Python AST** only. Non-Python
repos get containment + same_file_next but no semantic call/reference edges, so graph
retrieval quality is **language-skewed**. The spec for fair cross-language benchmarking
would require parity (e.g., tree-sitter for all languages).

## Expansion — `graph_candidate_expander.py`

From a seed set (vector hits), traverse edges up to a bounded depth, accumulating
neighbor scores with per-hop decay and per-edge-kind weight.

`graph_expansion_profile_factory.py` selects edge weights + traversal depth per query
type (semantic / path_symbol / workflow). This is the "query-aware typed GraphRAG"
feature.

**Contract**: traversal is bounded (depth + neighbor cap) to avoid blow-up; seed scores
feed the decay.
⚠️ Divergence: seed scores arrive from `_normalize`, which collapses ties to 1.0 (R-1);
in degenerate cases every neighbor inherits full seed weight regardless of seed rank.

## Persistence — `graph/code_graph_store.py`

Serializes `CodeGraph` to JSON alongside the vector index.
⚠️ (R-11) `GraphRetrievalStrategy._load_graph` does not check `exists()` before
`load()` — missing artifact raises rather than degrading.

## Graph invariants (intended)

1. Edges typed + weighted; bidirectional neighbor lookup.
2. Bounded traversal (depth, neighbor count, decay).
3. Optional and non-blocking for vector indexing.
4. ⚠️ *Aspirational*: language parity for call/reference edges (currently Python-only).

## Test coverage

`tests/unit/test_code_graph_builder.py`, `test_graph_retrieval_strategy.py`,
`test_graph_candidate_expander.py` exist. ⚠️ `graph_neighbor_index.py` and the
expansion-profile-by-query-type selection are not directly covered (⚠️ 3.1).
