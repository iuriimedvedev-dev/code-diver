# Code Diver RAG

Use the local `code-diver` CLI for repository retrieval:

- Build or refresh the index with `code-diver index`.
- Search repository context with `code-diver search "<query>"`.
- Open the best matching code location with `code-diver open "<query>"`.
- Inspect the repository read-only with `code-diver tree`, `code-diver grep`, and `code-diver rg`.
- Run retrieval evaluations with `code-diver evaluate`.

Prefer the CLI artifact over ad hoc full-repo reads when a question needs targeted code context.
Inside Pi, use only the registered `code_diver_*` tools. This assistant is read-only: do not edit, write, delete, move, format, or patch files.
