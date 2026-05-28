# Code Diver RAG

Use the local `code-diver` CLI for repository retrieval:

- Build or refresh the index with `code-diver index`.
- Search repository context with `code-diver search "<query>"`.
- Open the best matching code location with `code-diver open "<query>"`.
- Run retrieval evaluations with `code-diver evaluate`.

Prefer the CLI artifact over ad hoc full-repo reads when a question needs targeted code context.
Inside Pi, prefer the registered tools `code_diver_search`, `code_diver_index`, `code_diver_open`, and `code_diver_evaluate` instead of shelling out manually.
