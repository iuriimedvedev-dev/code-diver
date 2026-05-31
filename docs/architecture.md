# Code Diver Architecture

Code Diver is a config-first sandbox for codebase search experiments. The CLI is the stable entrypoint. Research evals use a direct provider-backed orchestrator; Pi remains an optional interactive `ask`/`chat` backend.

## Main Flow

1. `code-diver index` scans a repository, builds code items, embeds them, and stores vectors in the configured store.
2. `code-diver search` embeds a query and retrieves relevant code items.
3. `code-diver evaluate` runs a fixed dataset through a retrieval strategy and emits quality and latency metrics.
4. `code-diver evaluate-indexing` asks an AI orchestrator to build an isolated selected index, then evaluates that index with the same dataset.

## Hybrid Indexing

The scanner can now build three complementary index item types in one artifact:

| `index_kind` | Built from | Best role |
| --- | --- | --- |
| `chunk` | Fixed-size source line ranges. | Evidence snippets and broad semantic retrieval. |
| `symbol` | Classes/functions/methods extracted from source. | API, command, handler, class, function, and identifier queries. |
| `file_summary` | Per-file summary item with imports, symbols, and leading non-empty lines. | File-level recall candidate; should usually be downweighted for top-rank evidence. |

The hybrid retriever can apply `hybrid_search.item_kind_weights` after vector/lexical/path/symbol/graph scoring. This lets experiments keep multiple index types in Qdrant while controlling which item type is allowed to dominate ranking.

The search tool payload includes `indexKind`, so orchestrator logs can show whether a candidate came from chunk, symbol, or file-summary indexing.

## Core Boundaries

| Layer | Responsibility |
| --- | --- |
| Config | YAML-owned provider, storage, scanner, graph, agent, and experiment settings. |
| Providers | Provider-agnostic embedding and generation implementations. |
| Stores | JSON and Qdrant vector persistence. Local Qdrant is the default serious store. |
| Inspection | Read-only repo tools: tree, symbols, grep, rg, read, inspect. |
| Indexing | Scanner index, AI-selected index, plugins, AST GraphRAG graph build. |
| Retrieval | Vector, recursive, graph, and orchestrated retrieval strategies. |
| Evaluation | Dataset loading, metric computation, route-bucket diagnostics, item-kind diagnostics, experiment and indexing-hypothesis runs. |
| Pi Extension | Optional interactive backend for `ask`/`chat`; not used by reproducible eval runs. |

## Agent Tool Modes

The direct orchestrator receives only the tools allowed by the selected hypothesis:

- `vector_search`: vector search plus read-only verification tools.
- `grep_search`: tree, symbols, grep, rg, read, inspect; no vector search.
- `indexing`: read-only inspection plus `code_diver_index_selected`.
- single-tool indexing hypotheses: one discovery tool plus `code_diver_index_selected`.

`code_diver_index_selected` accepts only paths and line ranges. The model cannot inject arbitrary indexed content; the CLI reads the files from disk and enforces repository-root and gitignore guards.

## Qdrant Isolation

Indexing evals must not share a collection. `evaluate-indexing` creates a collection per hypothesis and run id:

```text
<base_collection>_<hypothesis>_<run_id>
```

This prevents later AI runs from benefiting from earlier runs.

## Logging

Every `evaluate-indexing` direct orchestrator run writes a JSONL log:

```text
.code-diver/traces/orchestrator-indexing/<run_id>/<hypothesis>.jsonl
```

The log contains the full direct orchestrator transcript: prompts, model JSON responses, tool calls, tool results, usage/cost estimates, selected index items, and persistence events.

`evaluate-search-tools` writes similar logs under:

```text
.code-diver/traces/orchestrator-search/<run_id>/<hypothesis>.jsonl
```

## Pi Decision

Pi is no longer the research backbone. It is useful for interactive UX, but evals need stable logs, direct provider control, reproducible tool traces, and consistent metrics.

The current eval backbone is direct:

- `DirectIndexingOrchestrator` for selected-index construction.
- `DirectSearchOrchestrator` for tool-only search comparisons.
- `DirectToolExecutor` for read-only, gitignore-aware tools.
