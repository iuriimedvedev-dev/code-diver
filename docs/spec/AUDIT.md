# Code Diver — Architecture & Code Audit

**Date:** 2026-06-01 · **Scope:** full `src/code_diver` (190 files, ~10k LOC, 101 tests)
· **Method:** read-only review of core retrieval/agent/indexing + cross-cutting concerns.
**No code was changed.** Each finding cites `file:line` and maps to a spec contract in
this folder.

---

## Remediation status — updated 2026-06-01

The **P0 security & trust cluster is RESOLVED.** Untrusted-model-output-to-side-effect
findings (Theme B) and the Vertex batching regression are fixed and covered by tests:

- **A-4** — `PathGuard` is now applied at the `DirectToolExecutor` boundary via
  `_validated_optional_path` / `_validated_required_path`; every path arg is confined to
  root. Test: `test_direct_tool_executor_rejects_path_escape_at_executor_boundary`.
- **A-3 / A-8** — `code_diver_inspect.reads[]` now counts against `max_inspect_reads`
  (default 10); oversized inspects return a structured budget-error. Tests:
  `test_direct_tool_executor_caps_inspect_reads`,
  `test_direct_search_orchestrator_counts_inspect_reads_against_budget`.
- **I-5 / I-6** — `IndexPlanSanitizer.safe_exclude_additions` now rejects hidden
  patterns, broad globs (`*.py`, `**/*`) and over-limit patterns;
  `OrchestratedCodebaseScanner` logs `index_plan_rejected_include/exclude`. Test:
  `test_orchestrated_scanner_rejects_broad_ai_excludes`.
- **I-4** — `AiCodebaseScanner` now catches generation/parse errors, records
  `last_error`, and falls back to the base scanner. Test:
  `test_ai_codebase_scanner_falls_back_to_base_scan_on_generation_error`.
- **2.1** — `VertexEmbeddingProvider` now delegates to the batching parent instead of
  one API call per document. Test: `test_vertex_embedding_provider_reuses_embedding_2_contract`.

**Still open (UNRESOLVED):**
- **R-1 / R-2 / R-4 / R-5 / R-6 / R-7** — scoring contract + golden tests (Theme C).
- **R-8 / A-1** — explicit degradation visibility (`degraded` flag, no silent fallback).
- **I-1 / I-10** — embedding retry + partial-save in `IndexingService`.
- **P2 observability** — unified trace schema + tracing on the retrieval/embedding hot paths.

---

## Verdict

> Code Diver is **competent at the small scale and fragile at the medium scale.** The
> core abstractions (EmbeddingProvider, VectorStore, RetrievalStrategy) are clean
> Protocols with factories, and the config system is consistent. But the project's
> stated principles — *screaming architecture, fail-fast, no magic values* — are
> contradicted in exactly the places that decide its output quality and trust:
> retrieval scoring, agent sandboxing, and reproducibility.

The three things we most clearly **do wrong**:

1. **We hide failures instead of failing fast.** Silent `except Exception` fallbacks in
   the orchestrators, the LLM reranker, and the AI scanner mean a broken step looks
   identical to a working one. For a *benchmarking* tool, this silently corrupts results.
2. **We trust the model with the filesystem.** The agent tool executor passes
   LLM-supplied paths straight to file services with no path guard, and the read budget
   is trivially bypassed. This is a real security boundary that is open.
3. **We can't trust our own scores.** Per-query min-max normalization, weight profiles
   that don't sum to 1.0, non-standard BM25, and a query-length-biased coverage metric
   make retrieval scores ordinal-at-best and incomparable across queries/configs — the
   exact opposite of what a reproducible eval platform needs.

Underneath those: **18% module test coverage**, **two divergent trace formats**, **no
tracing on the retrieval hot path**, and `cli.py` (1,041 lines) acting as the real eval
engine.

---

## Top findings (ranked, all subsystems)

| # | Sev | ID | Finding | Location |
|---|-----|----|---------|----------|
| 1 | 🔴 Critical | A-4 | LLM-supplied `path` args passed to file services with **no path guard** — traversal outside repo root possible — ✅ FIXED (2026-06-01) | `agent/direct_tool_executor.py:44` |
| 2 | 🟠 High | I-5 | LLM `exclude` patterns **bypass the sanitizer** — injected response can suppress indexing of whole languages — ✅ FIXED (2026-06-01) | `orchestration/orchestrated_codebase_scanner.py:38` |
| 3 | 🟠 High | A-1 | Blanket `except Exception` in both orchestrators discards tracebacks; bugs look like network errors | `agent/direct_search_orchestrator.py:113` |
| 4 | 🟠 High | R-8 | `LlmRerankRetrievalStrategy` silently returns unranked candidates on any error — invisible to caller | `strategies/llm_rerank_retrieval_strategy.py:69` |
| 5 | 🟠 High | I-1 | No retry/partial-save in embedding — **one transient error aborts the whole index** | `services/parallel_embedding_service.py:38` |
| 6 | 🟠 High | I-4 | `AiCodebaseScanner.scan` has no error handling around LLM call / `json.loads` — crashes the index — ✅ FIXED (2026-06-01) | `ai_indexing/ai_codebase_scanner.py:28` |
| 7 | 🟠 High | A-3 | `code_diver_inspect.reads[]` bypasses `MAX_READ_CALLS`; indexing orchestrator has no budget at all — ✅ FIXED (2026-06-01) | `agent/direct_search_orchestrator.py:192` |
| 8 | 🟠 High | 2.1 | `VertexEmbeddingProvider` embeds **one doc per API call**, defeating batching (400 calls vs ~13) — ✅ FIXED (2026-06-01) | `providers/vertex_embedding_provider.py:50` |
| 9 | 🟠 High | 5.1 | `cli.py` (1,041 lines) holds eval metrics, graph factory, experiment mutation — breaks its own boundary | `cli.py` |
| 10 | 🟠 High | 3.1 | ~139/169 source modules have **no direct test**; ExperimentRunner, Gemini gen, CodebaseScanner glob path untested | `tests/` |
| 11 | 🟠 High | 1.2 | Config validation is structural only — bad weights/dims/mode/strategy fall back silently, not fail-fast | `config/config_loader.py` |
| 12 | 🟠 High | 1.5 | ClickHouse password hardcoded (`code_diver`) in 7 YAMLs, no env indirection | `config/metrics_config.py:14` |
| 13 | 🟠 High | 4.1 | Two incompatible trace systems (`"timestamp"` vs `"ts"`), neither uses stdlib `logging` | `tracing/trace_logger.py` vs `agent/direct_agent_logger.py` |
| 14 | 🟠 High | R-1 | `_normalize` maps all tied/single scores to `1.0` — inflates graph seeds, breaks cross-query comparability | `strategies/hybrid_retrieval_strategy.py:164` |
| 15 | 🟡 Med | R-5 | Weight profile `ROUTE_WORKFLOW` sums to 0.92 (not 1.0); no invariant enforces it — routes incomparable | `strategies/hybrid_query_router.py:92` |
| 16 | 🟡 Med | R-4 | Per-query min-max on cosine scores destroys cross-query semantics; normalized twice | `strategies/hybrid_retrieval_strategy.py:79,127` |
| 17 | 🟡 Med | R-7 | Non-standard BM25: title/path/metadata tokens doubled → distorted TF saturation | `strategies/hybrid_lexical_index.py:62` |
| 18 | 🟡 Med | R-6 | Coverage = matches / `len(query.terms)` — penalizes long queries, ignores doc density | `strategies/hybrid_candidate_scorer.py:39` |
| 19 | 🟡 Med | R-2 | Vector RRF channel includes `vector_score == 0` items — unearned contribution | `strategies/hybrid_retrieval_strategy.py:196` |
| 20 | 🟡 Med | R-10 | Recursive expansion anchors on original query, not current — caps deep-round recall | `strategies/recursive_retrieval_strategy.py:36` |
| 21 | 🟡 Med | R-11 | `GraphRetrievalStrategy._load_graph` raises on missing graph; Hybrid degrades — inconsistent | `strategies/graph_retrieval_strategy.py:58` |
| 22 | 🟡 Med | I-7 | Fixed-stride chunking, **no overlap** — symbols split across chunk boundaries | `services/codebase_scanner.py:153` |
| 23 | 🟡 Med | I-3 | No incremental indexing — every build overwrites the full index | `services/indexing_service.py:65` |
| 24 | 🟡 Med | I-10 | `workers=1` (default) skips batching entirely — `batch_size` is dead config | `services/parallel_embedding_service.py:25` |
| 25 | 🟡 Med | A-2 | `asyncio.run()` in parallel executor raises inside an existing event loop | `agent/parallel_tool_executor.py:15` |
| 26 | 🟡 Med | A-9 | Observation compressor unconditionally strips `matches` — model loses found-result context | `agent/tool_observation_compressor.py:21` |
| 27 | 🟡 Med | A-5 | JSON parser returns **first** action object — scratchpad JSON can shadow real answer | `agent/json_response_parser.py:10` |
| 28 | 🟡 Med | X-2 | Hybrid lazy caches mutated with no locking — race under concurrent search | `strategies/hybrid_retrieval_strategy.py:40` |
| 29 | 🟡 Med | 2.2 | `generate_json_result` on Protocol but callers still `getattr`-fallback → forked token accounting | `agent/direct_search_orchestrator.py:120` |
| 30 | 🟡 Med | 2.5 | Qdrant `append()` dim-check skipped on empty collection → mixed-dimension corruption | `store/qdrant_vector_store.py:87` |
| 31 | 🟡 Med | 4.2 | No tracing on vector/recursive/hybrid retrieval or any embedding call | retrieval + providers |
| 32 | 🟡 Med | 1.3 | `MAX_FILE_BYTES` magic `1_000_000` re-declared in 8+ constructors, ignores `Defaults` | multiple |
| 33 | 🟡 Med | 5.4 | 13+ YAML configs duplicate the full schema; no inheritance | root + `configs/` |
| 34 | 🟡 Med | 5.2 | `strategies/` over-fragmented (24 files, ~50 LOC avg, 9-line data classes) | `strategies/` |
| 35 | 🟢 Low | A-6/A-7 | Token estimate replaces real `0`-token counts; unknown models → `$1.50/$9.00` default | `agent/model_cost_estimator.py` |
| 36 | 🟢 Low | I-2 | Embedding text truncated at char (not token) boundary | `services/embedding_text_preparer.py:14` |
| 37 | 🟢 Low | X-1 | Tokenizer emits whole + split identifier tokens → TF double-count | `services/tokenizer.py:8` |
| 38 | 🟢 Low | 5.3 | `_uses_embedding_2()` hardcoded model-name branch controls API format | `providers/gemini_embedding_provider.py:88` |
| 39 | 🟢 Low | 2.6 | No secret redaction before trace JSONL write | `tracing/trace_logger.py` |

(Full per-finding evidence, with code excerpts, is in the two source audits; this table
is the consolidated, deduplicated view.)

---

## Root-cause themes

The 39 findings cluster into five systemic causes — fix the cause, not the symptom:

### Theme A — Fail-silent instead of fail-fast
A-1, R-8, I-1, I-4, R-11, 4.3. The codebase says "fail-fast" but the hot paths swallow
exceptions and substitute defaults. **Consequence:** broken steps are invisible, and a
benchmarking tool reports confident-but-wrong numbers. *Decision needed:* distinguish
"harness resilience" (one eval case may fail without aborting the run) from "silent
correctness loss" (a rerank/scan/index step quietly degrading). The first is legitimate;
the second is a bug. Add a debug re-raise and an explicit `degraded: bool` signal on
results.

### Theme B — Untrusted model output reaches side effects
A-4, I-5, I-6, A-3, A-5. LLM output flows into filesystem reads and index plans with
gaps in sanitization and budget enforcement. **Consequence:** path traversal, indexing
suppression, budget bypass — all reachable via prompt-injection from a scanned repo's
own files. *This is the highest-priority cluster.* One reusable validation boundary
(PathGuard everywhere + sanitize all LLM patterns including `exclude` + count
`inspect.reads` against the budget) closes most of it.

### Theme C — Scores are not trustworthy or reproducible
R-1, R-2, R-4, R-5, R-6, R-7, X-1. The fusion math has correctness and
comparability defects, and none of the edge cases are tested. **Consequence:** the
metrics the project produces to compare strategies are built on incomparable scores.
*Decision needed:* define the scoring contract precisely (normalization scheme, weight
invariant, BM25 variant, coverage definition) and pin it with golden tests.

### Theme D — Thin, mislocated tests + missing observability
3.1, 3.2, 3.3, 4.1, 4.2, 5.1. 18% module coverage, the eval engine living in `cli.py`,
two trace schemas, and no tracing on the retrieval path. **Consequence:** regressions
like the Vertex batching bug (2.1) ship undetected and are diagnosed by manual runs.

### Theme E — Configuration & structure ceremony
1.1, 1.2, 1.3, 1.4, 1.5, 5.2, 5.4. Heavy config surface, structural-only validation,
duplicated magic numbers, raw-string provider selection, hardcoded secrets, 13+
copy-pasted YAMLs, over-fragmented `strategies/`. **Consequence:** the abstraction tax
is paid without the safety it promises.

---

## Remediation roadmap

Ordered by risk-reduction per unit effort.

### P0 — Security & trust (do first)
- **Apply `PathGuard` in `DirectToolExecutor`** for every path arg (A-4). One choke point.
- **Sanitize all LLM-supplied patterns**, including `exclude`, in `OrchestratedCodebaseScanner` (I-5, I-6).
- **Count `inspect.reads[]` against `MAX_READ_CALLS`** and add a read/round budget to the indexing orchestrator (A-3, A-8).
- **Wrap `AiCodebaseScanner` LLM call + JSON parse** in graceful handling, matching `IndexPlanOrchestrator` (I-4).

### P1 — Correctness of the product's output
- **Define & pin the scoring contract**: fix `_normalize` degenerate case (R-1), enforce weight-sum invariant (R-5), stop per-query re-normalization or document it as ordinal (R-4), filter zero-vector items from the vector RRF channel (R-2), fix coverage denominator (R-6), decide on standard vs weighted BM25 (R-7, X-1). Add golden tests for each.
- **Make LLM rerank failures observable** — surface a `degraded` flag, not a silent fallback (R-8).
- **Embedding resilience**: honor `EMBEDDING_RETRY_ATTEMPTS`, partial-save, and fix Vertex per-doc batching (I-1, I-10, 2.1).
- **Replace blanket `except Exception`** with typed handling + debug re-raise in orchestrators (A-1, 4.3).

### P2 — Reproducibility & observability
- **Unify the two trace systems** into one schema on stdlib `logging`; trace the retrieval hot path and embedding calls (4.1, 4.2, 4.4).
- **Extract the eval engine out of `cli.py`** into services (5.1).
- **Raise coverage on the hot paths**: hybrid scoring/fusion edge cases, ExperimentRunner, Qdrant `append()` dimension guard, Gemini generation retry/fallback (3.1–3.3, 3.5, 2.5).

### P3 — Hygiene
- Semantic config validation at load (1.2); single source for `MAX_FILE_BYTES` (1.3); `GenerationProviderId` enum (1.4); ClickHouse env indirection + secret redaction (1.5, 2.6); YAML inheritance/overlay (5.4); consolidate trivial `strategies/` data classes (5.2); chunk overlap (I-7); incremental indexing (I-3).

---

## Cross-references

Each spec in this folder ends with an "invariants (intended vs actual)" table whose ❌
rows correspond to the findings above:
[domain](./01-domain-model.md) · [indexing](./02-indexing.md) ·
[retrieval](./03-retrieval-strategies.md) · [hybrid](./04-hybrid-search.md) ·
[graph](./05-graph.md) · [agent](./06-agent-orchestration.md) ·
[providers/storage](./07-providers-and-storage.md) ·
[eval](./08-evaluation-and-experiments.md) · [config/CLI](./09-configuration.md).
