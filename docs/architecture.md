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

## Modern GraphRAG

The graph artifact is deterministic and AST-derived. It is rebuilt by `code-diver index` when `graph.enabled=true`.

Current node set:

- all indexed `chunk`, `symbol`, and `file_summary` items;
- plugin and AI-selected items when those indexers are used.

Current typed edge set:

| Edge kind | Meaning |
| --- | --- |
| `same_file_next` | Adjacent line-ranged items in the same file. |
| `summarizes` | A `file_summary` item points to chunks/symbols in the same file. |
| `imports` | Source file imports another indexed file. |
| `references` | Item text references a known indexed symbol name under hard per-source budgets. |
| `contains` | AST/file range containment: chunk -> symbol, class -> method. |
| `calls` | Python AST call edge from one symbol item to another likely symbol target. |

Retrieval does not traverse all edges uniformly. `GraphExpansionProfileFactory` selects a route-specific traversal profile:

- `semantic`: vector-first, shallow and low graph weight;
- `path_symbol`: containment/symbol/same-file oriented;
- `workflow`: deeper traversal with stronger `calls`, `references`, and `imports`.

`GraphCandidateExpander` is shared by standalone `graph` retrieval and hybrid retrieval. It uses directed and reverse edge weights separately, bounded depth, bounded neighbors, and score decay per hop.

## Core Boundaries

| Layer | Responsibility |
| --- | --- |
| Config | YAML-owned provider, storage, scanner, graph, agent, and experiment settings. |
| Providers | Provider-agnostic embedding and generation implementations. |
| Stores | JSON and Qdrant vector persistence. Local Qdrant is the default serious store. |
| Inspection | Read-only repo tools: tree, symbols, grep, rg, read, inspect. |
| Indexing | Scanner index, AI-selected index, plugins, AST GraphRAG graph build. |
| Retrieval | Vector, recursive, graph, hybrid, and bounded LLM-rerank retrieval strategies. |
| Evaluation | Dataset loading, metric computation, route-bucket diagnostics, item-kind diagnostics, experiment and indexing-hypothesis runs. |
| Pi Extension | Optional interactive backend for `ask`/`chat`; not used by reproducible eval runs. |

## Agent Tool Modes

The direct orchestrator receives only the tools allowed by the selected hypothesis:

- `vector_search`: vector search plus read-only verification tools.
- `grep_search`: tree, symbols, grep, rg, read, inspect; no vector search.
- `indexing`: read-only inspection plus `code_diver_index_selected`.
- single-tool indexing hypotheses: one discovery tool plus `code_diver_index_selected`.
- `ai_search_hybrid_orchestrator`: the universal hybrid search hypothesis. It exposes `code_diver_search`, tree, symbols, grep, rg, read, and inspect together.

`code_diver_index_selected` accepts only paths and line ranges. The model cannot inject arbitrary indexed content; the CLI reads the files from disk and enforces repository-root and gitignore guards.

## Universal Hybrid Orchestrator

The universal search agent is intentionally provider-agnostic. It is built from three small pieces:

| Component | Role |
| --- | --- |
| `ToolManifestBuilder` | Emits a structured manifest for only the tools enabled by the active YAML hypothesis. Each row describes stage, parallel safety, best cases, bad cases, return shape, and arguments. |
| `DirectSearchPromptBuilder` | Turns the manifest into a tool-routing prompt. The prompt tells the model which tool family is strongest for semantic, path/config, symbol, workflow, and exact-string queries. |
| `ParallelToolExecutor` | Runs independent tool calls from one model response concurrently with a bounded semaphore. Search and indexing orchestrators both use it. |

The intended model behavior is a hybrid plan, not a fixed codebase-specific script:

- semantic or informal queries start from `code_diver_search`, which already combines vector, BM25, symbol metadata, and query-aware GraphRAG;
- path/config/package/docker/frontend queries add `tree` or narrow `rg` probes;
- class/function/handler/service/model queries add `symbols`;
- workflow queries add structural probes and rely on GraphRAG candidates from `code_diver_search`;
- exact strings, keys, flags, and error names use `grep` or `rg`;
- `read` is reserved for bounded verification of top candidates.

The model can put several cheap probes in the same `tool_calls` array. The runtime preserves result ordering while executing those probes asynchronously, so a hybrid first round can gather vector, lexical, symbol, and repository-map signals without extra model turns.

Search verification reads are budgeted. `DirectSearchOrchestrator` allows at most 10 `code_diver_read` calls per case; extra reads return a structured budget error while other tools in the batch still run. The intended flow is candidate generation through `code_diver_search`, cheap verification through `grep`/`rg` or scoped symbols, and only then small targeted reads for final evidence.

## Bounded LLM Rerank

`hybrid_rerank` is the current highest-quality research path. It keeps candidate discovery deterministic and uses the model only once:

1. `HybridRetrievalStrategy` gathers vector, lexical/BM25, path, symbol, and graph candidates.
2. `LlmRerankPromptBuilder` sends a compact candidate table to the configured generation provider.
3. `LlmRerankResponseParser` accepts only JSON candidate indices, ignoring invalid or invented references.
4. `LlmRerankRetrievalStrategy` returns the selected order, then fills any remaining slots with the original hybrid order.

This keeps the model below the tool boundary. It cannot read files, call grep, or continue planning; it only reranks bounded candidates. Trace events `llm_rerank_prompt`, `llm_rerank_response`, and `llm_rerank_error` record prompts, selected indices, provider usage, latency, and estimated cost.

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
