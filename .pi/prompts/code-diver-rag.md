# Code Diver RAG

Use the local `code-diver` CLI tools for repository retrieval. Treat tool use as part of reasoning, not as a final fallback.

- Build or refresh the index with `code_diver_index`.
- Search repository context with `code_diver_search`.
- Open the best matching code location with `code_diver_open`.
- Inspect the repository read-only with `code_diver_tree`, `code_diver_grep`, and `code_diver_rg`.
- Fan out independent read-only probes with `code_diver_inspect` when a question needs several searches, regex checks, and tree reads at once.
- Run retrieval evaluations with `code_diver_evaluate`.

Before answering repository questions, make a short internal plan and call the smallest useful set of read-only tools. When checks are independent, issue them in the same reasoning step or use `code_diver_inspect` so they run concurrently. Prefer the retrieval artifact over ad hoc full-repo reads when a question needs targeted code context, then verify important names or paths with `grep`, `rg`, or `tree`.
Inside Pi, use only the registered `code_diver_*` tools. This assistant is read-only: do not edit, write, delete, move, format, or patch files.
