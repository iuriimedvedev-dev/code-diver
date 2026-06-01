# Deterministic Indexing Strategy

The active indexing strategy is comprehensive and non-agentic. The indexer should never depend on a model deciding which files are important. Models are used only after the artifact exists: query planning, tool routing, reranking, and targeted verification.

## Pipeline

1. Traverse the repository with configured include/exclude rules and gitignore-aware inspection services.
2. Create fixed line chunks for broad semantic coverage.
3. Create structural chunks from AST spans where supported, with generic symbol spans as fallback.
4. Create symbol items for classes, functions, methods, interfaces, and similar declarations.
5. Create file-summary items with path, imports, symbols, and leading source context.
6. Embed all item types with the configured local/API provider.
7. Save vectors and payloads into the configured store, normally local Qdrant.
8. Build the deterministic GraphRAG artifact: same-file, summary, imports, references, containment, and AST call edges.
9. During search, let the LLM orchestrator combine vector/BM25/GraphRAG candidates with grep, rg, symbols, read, inspect, and rerank tools.

## Why No AI During Indexing

AI-selected indexing undercovered real repositories in earlier experiments. It was slower, less reproducible, and vulnerable to prompt noise from repository contents. Large repositories such as IntelliJ also need predictable parallel scanning and bounded cost. A deterministic artifact lets us compare search hypotheses against the same corpus instead of mixing search quality with index-construction variance.

## Required Observability

Each index run writes composition metrics in the `index_items_prepared` trace event:

```json
{
  "indexed_items": 1234,
  "unique_paths": 321,
  "items_by_kind": {
    "chunk": 700,
    "file_summary": 321,
    "structural_chunk": 100,
    "symbol": 113
  },
  "paths_by_kind": {
    "chunk": 321,
    "file_summary": 321,
    "structural_chunk": 80,
    "symbol": 70
  }
}
```

The CLI also prints a compact composition line after `code-diver index`. Search logs keep `indexKind` on every candidate so failures can be analyzed by index type.

## Active Search Role For LLMs

The search agent can use read-only tools only:

- `code_diver_search` for hybrid vector/BM25/symbol/GraphRAG candidates.
- `code_diver_tree` for repository map and package layout.
- `code_diver_symbols` for declaration-oriented queries.
- `code_diver_grep` and `code_diver_rg` for exact strings, config keys, commands, flags, and error names.
- `code_diver_inspect` for concurrent structured summaries.
- `code_diver_read` for bounded verification of top candidates.
- `code_diver_rerank` for AI ranking over structured candidates.

No active search hypothesis exposes write-capable indexing tools.
