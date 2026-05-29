# Code Diver Architecture

Code Diver is a config-first sandbox for codebase search experiments. The CLI is the stable entrypoint; Pi is currently one agent backend that can call Code Diver tools.

## Main Flow

1. `code-diver index` scans a repository, builds code items, embeds them, and stores vectors in the configured store.
2. `code-diver search` embeds a query and retrieves relevant code items.
3. `code-diver evaluate` runs a fixed dataset through a retrieval strategy and emits quality and latency metrics.
4. `code-diver evaluate-indexing` asks an AI orchestrator to build an isolated selected index, then evaluates that index with the same dataset.

## Core Boundaries

| Layer | Responsibility |
| --- | --- |
| Config | YAML-owned provider, storage, scanner, graph, Pi, and experiment settings. |
| Providers | Provider-agnostic embedding and generation implementations. |
| Stores | JSON and Qdrant vector persistence. Local Qdrant is the default serious store. |
| Inspection | Read-only repo tools: tree, symbols, grep, rg, read, inspect. |
| Indexing | Scanner index, AI-selected index, plugins, AST GraphRAG graph build. |
| Retrieval | Vector, recursive, graph, and orchestrated retrieval strategies. |
| Evaluation | Dataset loading, metric computation, experiment and indexing-hypothesis runs. |
| Pi Extension | Exposes Code Diver tools to the Pi agent without source editing capabilities. |

## Agent Tool Modes

Pi receives only the tools allowed by the selected hypothesis:

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

Every `evaluate-indexing` Pi run writes a JSONL log:

```text
.code-diver/traces/orchestrator-indexing/<run_id>/<hypothesis>.jsonl
```

The log contains Pi JSON events, assistant messages, tool results, usage/cost records, stderr events, fallback events, and runner command boundaries.

## Pi Backbone Decision

Pi is useful as the interactive CLI backbone because it already handles model routing, tool registration, sessions, and user-facing agent UX. It is less ideal as the only research runner because we need stable logs, exact cost accounting, timeout control, and reproducible tool-call traces.

The architecture should keep Pi as one backend, not the backend. The next clean step is an `AgentRunner` abstraction with:

- `PiAgentRunner` for interactive use and compatibility with Pi tools.
- `DirectGeminiAgentRunner` using Google GenAI function calling for controlled evals.

That lets us compare the same tool manifests through Pi and through direct provider APIs while keeping metrics and logs consistent.
