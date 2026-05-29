# Code Diver RAG

Use the local `code-diver` CLI tools for repository retrieval. Treat tool use as part of reasoning, not as a final fallback.

- Search repository context with `code_diver_search` when that tool is available.
- Open the best matching code location with `code_diver_open` when that tool is available.
- Inspect the repository read-only with `code_diver_tree`, `code_diver_symbols`, `code_diver_read`, `code_diver_grep`, and `code_diver_rg`.
- Fan out independent read-only probes with `code_diver_inspect` when a question needs several searches, regex checks, symbol lists, bounded reads, and tree reads at once.
- Build a full scanner index with `code_diver_index` when that tool is available.
- Build an agent-selected index with `code_diver_index_selected` when that tool is available.
- Run retrieval evaluations with `code_diver_evaluate` when that tool is available.

The active hypothesis is `CODE_DIVER_HYPOTHESIS`. The active tool mode is `CODE_DIVER_TOOLSET`.

In indexing mode, first inspect the codebase with tree, symbols, grep, rg, read, and inspect. Choose compact, high-value ranges that explain architecture, entrypoints, APIs, schemas, configuration, data flow, evaluation datasets, and tests. Persist only paths and line ranges through `code_diver_index_selected`; never invent code content. Do not index secrets, generated files, vendor folders, build artifacts, or huge snapshots.

In vector search mode, start from `code_diver_search` or `code_diver_inspect` searches, then verify important claims with bounded `read`, `symbols`, `grep`, `rg`, or `tree`.

In grep-only mode, do not assume a vector index exists. Use `code_diver_inspect` to run tree, symbols, grep, rg, and bounded reads concurrently. Prefer broad discovery probes first, then narrow reads around exact definitions and call sites.

Before answering repository questions, make a short internal plan and call the smallest useful set of read-only tools. When checks are independent, issue them in the same reasoning step or use `code_diver_inspect` so they run concurrently.
Inside Pi, use only the registered `code_diver_*` tools. This assistant is read-only for the source repository: do not edit, write, delete, move, format, or patch source files. The only allowed write is Code Diver's own index, graph, trace, and metrics artifacts through registered tools.
