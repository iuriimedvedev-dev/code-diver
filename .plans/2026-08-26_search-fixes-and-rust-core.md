# Plan: obvious search fixes + Rust search core

## A. Obvious Python fixes (first)
1. Token-aware truncation in `_bounded_prefixed` / `embedding_text_preparer.py` (task #64). Catch-and-shrink vs 512-token ceiling. Tests with dense Java-like punctuation.
2. Scanner excludes: `**/testSrc/**`, `**/testSources/**`, `**/platform-tests/**`. Champion YAML: do not change unless experiment config; add to defaults + IntelliJ experiment yml if needed.
3. Do not reindex champion. Do not promote H-5.

## B. Rust search core (parallel, incremental)
Target: hybrid retrieval + graph-file scoring + rerank glue callable from Python (PyO3). CLI/eval/config stay Python.
Landing: inverted BM25 + hybrid candidate fusion (SWE-bench 48s path), then graph-file O(n) scorer, then CE batch glue.
Out of scope v1: embedding servers, Qdrant, llama.cpp.

## C. Quality vs jbcontext (after A)
H-1 incremental file-purpose prose; H-3 listwise; eval #65 near-duplicates.
