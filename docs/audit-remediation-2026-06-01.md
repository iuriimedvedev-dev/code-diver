# Audit Remediation - 2026-06-01

This records the first remediation pass after the architecture audit in `docs/spec/AUDIT.md`.

## Fixed

| Audit ID | Fix | Tests |
| --- | --- | --- |
| A-4 | `DirectToolExecutor` now validates model-supplied path arguments at the executor boundary using `PathGuard` before calling read/tree/grep/rg/symbol services. | `test_direct_tool_executor_rejects_path_escape_at_executor_boundary` |
| A-3 | `DirectSearchOrchestrator` now counts `code_diver_inspect.reads[]` against `MAX_READ_CALLS`; oversized inspect batches return a structured budget error instead of executing hidden reads. | `test_direct_search_orchestrator_counts_inspect_reads_against_budget` |
| A-3 / A-8 | `DirectToolExecutor` has a per-inspect read cap for indexing and other non-search orchestrator paths. Extra reads are represented as structured budget-error sections. | `test_direct_tool_executor_caps_inspect_reads` |
| I-5 | AI-generated exclude patterns now pass through `IndexPlanSanitizer`; broad language-wide patterns such as `*.py` are rejected and traced. | `test_orchestrated_scanner_rejects_broad_ai_excludes` |
| I-4 | `AiCodebaseScanner` catches generation/parser failures, records `last_error`, and falls back to the base scanner rather than crashing the whole index run. | `test_ai_codebase_scanner_falls_back_to_base_scan_on_generation_error` |
| 2.1 | `VertexEmbeddingProvider.embed_documents()` now preserves Gemini batching instead of issuing one API call per document. | `test_vertex_embedding_provider_reuses_embedding_2_contract` |

## Verification

```text
uv run pytest tests/unit/test_direct_tool_executor.py tests/unit/test_direct_search_orchestrator.py tests/unit/test_orchestration.py tests/unit/test_ai_codebase_scanner.py tests/unit/test_vertex_providers.py
18 passed

uv run pytest
108 passed
```

## Still Open

- R-1/R-2/R-4/R-5/R-6/R-7: scoring contract and golden tests.
- R-8/A-1: make orchestrator and reranker degradation explicitly visible without swallowing programming errors.
- I-1/I-10: embedding retry/partial-save behavior in indexing service.
- P2 observability: unify trace schemas and trace retrieval/embedding hot paths.
