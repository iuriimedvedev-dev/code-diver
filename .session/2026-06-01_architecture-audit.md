# Session — Architecture Audit & Spec Backbone (2026-06-01)

## Goal
Analyse code-diver, audit it, and produce a spec "backbone" + report of what we do
wrong. **No code changes** — description only.

## What was done
- Mapped the full codebase (190 files, ~10k LOC, 21 packages, 101 tests) via Explore.
- Ran two deep read-only audits (core retrieval/agent/indexing; cross-cutting).
- Authored a spec backbone under `docs/spec/` (10 specs + index + audit report).

## Deliverables
- `docs/spec/README.md` — index + how to use
- `docs/spec/00-overview.md` … `09-configuration.md` — as-built specs with
  "invariants (intended vs actual)" tables
- `docs/spec/AUDIT.md` — 39 ranked findings, 5 root-cause themes, P0–P3 roadmap

## Headline conclusions (what we do wrong)
1. **Fail-silent, not fail-fast** — `except Exception` + silent fallbacks in
   orchestrators, LLM rerank, AI scanner. Broken steps look like working ones → corrupt
   eval results.
2. **Untrusted model output reaches the filesystem** — no PathGuard in the agent tool
   executor (Critical, A-4); LLM `exclude` patterns bypass sanitizer; read budget
   bypassable.
3. **Scores aren't trustworthy/reproducible** — per-query min-max normalization,
   weight profiles ≠ 1.0, non-standard BM25, query-length-biased coverage.
4. **18% module test coverage**, two divergent trace schemas, no tracing on the
   retrieval hot path, eval engine living in 1,041-line `cli.py`.

## Next steps (if approved)
- P0 security cluster first (PathGuard, sanitize excludes, budget enforcement, AI scanner
  error handling).
- P1 scoring contract + golden tests; embedding resilience (incl. Vertex batching bug).
- Then P2 observability/reproducibility, P3 hygiene.

## Notable single bug worth flagging
`VertexEmbeddingProvider` embeds one document per API call (defeats batching) —
`providers/vertex_embedding_provider.py:50`. Cheap, high-impact fix, no test guards it.
