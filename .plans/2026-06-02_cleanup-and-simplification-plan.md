# Cleanup & Simplification Plan — toward a clean, tested, stable `{index, search, eval}` tool

**Date:** 2026-06-02 · Synthesis of three read-only audits (clean-architecture, test-coverage,
CLI-collapse). Target end-state: **clean architecture, real correctness coverage, bug-free &
stable core, and a 3-command CLI `{index, search, eval}`** (from today's 15 commands).

## The unifying insight

The three goals are **one refactor, not three.** The same ~35% of the codebase —
`agent/` (1,803 LOC), `orchestration/` (541), `ai_indexing/` (311), `pi/` (418),
`plugins/` (98), `metrics/` (325) — is simultaneously:
- **reachable only through the 12 non-core commands** (and `mode=ai|orchestrated|hybrid`),
- **where almost every open fail-silent bug lives** (A-1, R-8, AG-1/2/3, P-1/3, I-4, I-5/6,
  1.5 hardcoded ClickHouse password), and
- **what bloats `cli.py` to 1,100 lines** (it *is* the eval/orchestrator engine).

So **collapsing the CLI to `{index, search, eval}` and pushing research behind an opt-in
`code-diver[research]` extra is the same act as the cleanup**: it removes ~3,470 LOC, shrinks
`cli.py` to ~250 lines of pure dispatch, and moves the riskiest fail-silent code off the
trusted product path — all at once.

## Current state (measured 2026-06-02)

| Dimension | Now | Target |
|-----------|-----|--------|
| CLI commands | **15** | **3** (`index`, `search`, `eval`) |
| `cli.py` | **1,100 LOC** (contains a *duplicate* eval-metric suite) | ~250 LOC, parse + dispatch only |
| Packages | 21 | ~12 core (+ optional `[research]`) |
| Line coverage | **80%** (unit+smoke) / 83% (all) | ≥80% **with correctness assertions on hot paths** |
| Tests | 147 (131 unit, e2e/protogen skip w/o sibling repo) | + ~10 P0/P1 characterization & bug tests |
| Open critical/high bugs | I-1W (critical), AG-1/AG-2, R-8/A-1, I-1 | 0 on the core path |

> Coverage caveat: 80% line coverage is **correctness-blind**. The R-1/R-2/R-5 scoring bugs
> *execute* in tests but nothing **asserts** them; `qdrant_vector_store.append()` (the sole
> streaming-write path, home of the I-1W critical bug) is **0% tested**; and the duplicate
> metric functions in `cli.py` are **0% tested** and already differ from `EvaluationService`
> (the cli copy misses the `::` symbol-id match) — so `direct_eval` and `evaluate` can report
> different numbers for the same data.

---

## Workstream A — Collapse the CLI to `{index, search, eval}`

Target surface (every command supports `--json` for scriptability):
```
code-diver index  [--config P] [--mode scanner|…] [--reindex] [--json]
code-diver search  QUERY [--config P] [--strategy …] [--limit N] [--open[=RANK]] [--json]
code-diver eval   [--config P] [--dataset P] [--strategy …] [--limit N] [--reindex] [--details] [--json]
```

Disposition of all 15:

| Command | Disposition |
|---------|-------------|
| `index`, `search`, `evaluate` | **KEEP** (`evaluate` → `eval`) |
| `open` | **DEMOTE → `search --open[=RANK]`** |
| `experiment` | single-strategy **FOLD → `eval --strategy`**; multi-hypothesis sweep + ClickHouse **DEFER → research** |
| `tree`, `grep`, `rg`, `read`, `symbols` | **REMOVE** (dev/inspection utilities; git/rg/editor do this) |
| `chat`, `ask` | **REMOVE / DEFER → research** (Pi backend, out of reproducible-eval scope) |
| `index-selected`, `evaluate-indexing`, `evaluate-search-tools` | **DEFER → research** (agent/orchestrator scaffolding; carry AG/I-1W traps) |

YAML-only knobs `search.strategy`, `indexing.mode`, `limit`, `dataset` become **flags** with
explicit precedence (flag > YAML > default) and **fail-fast validation** against
`RetrievalStrategyId` / valid modes (closes 1.2 on the core path).

Rollout: **deprecate** (add flags, warn on the 12) → **hide** (drop from `--help`) → **remove**
(print-and-exit stubs with a "moved to / removed" message, then delete). Keep `eval`'s implicit
auto-index-if-missing; gate explicit rebuild behind `--reindex`.

---

## Workstream B — Architecture cleanup

Ranked targets (full detail in the architecture audit; IDs S-1…S-5):

1. **S-1a (Critical): kill the duplicated metric algebra.** `cli.py:859-988` is a second
   copy of NDCG/MAP/precision/recall/hit that already differs from `EvaluationService`.
   Make `EvaluationService` accept a `(retrieved_paths, expected)` adapter so there is **one**
   metric implementation; delete the cli copy. *Lock behavior with a parity test first (C-P0).*
2. **S-1: extract the eval engine + factories out of `cli.py`** → `experiments/` runners +
   a `composition.py` composition root. `cli.py` → ~250 LOC. (Executes audit P2 / invariant #5.)
3. **S-5d: make `VectorStore` a real Protocol** declaring `append`, `count_items`, `close`,
   `replace_batches`; delete the `getattr`/`hasattr` probes (also resolves 2.2/2.5 surface).
4. **S-5b/c: break layering inversions** — move `ModelCostEstimator` out of `agent/` and
   `JsonResponse` out of `orchestration/` into neutral modules, so retrieval no longer depends
   on agent/orchestration. Unblocks removing those packages.
5. **S-3: consolidate over-fragmentation** — `strategies/` 26→~10 (merge the 7-file hybrid
   scorer into `hybrid_scoring.py`, the 6-file graph-expansion into `graph_expansion.py`);
   `config/` 25→~6; merge the 3 tiny `domain` kind/metadata files into `code_item.py`.
6. **S-2a: fold `RetrievalService` into `VectorRetrievalStrategy`** (remove a 1-method layer).
7. **4.1 / 4.4: unify the two trace schemas** (`"timestamp"` vs `"ts"`) onto one logger;
   introduce stdlib `logging` (zero `import logging` today) and stop `print()` for progress.

Lean package layout (post-cleanup): `cli` · `composition` · `domain` · `config` · `settings` ·
`scanning` · `indexing` · `embedding` · `store` · `retrieval` (vector+hybrid) · `eval` ·
`inspection` (path_guard + read tools used by search) · `tracing`. Everything else →
`code-diver[research]` extra / `code-diver-research` entrypoint.

Keep/delete/defer per package and a proposed layout are in the architecture audit's §7(b)/(c).

---

## Workstream C — Test coverage (characterization-first)

**Do BEFORE touching code (lock current behavior so the refactor is safe):**

| ID | Test | Why |
|----|------|-----|
| C-P0a | `_normalize` contract — single/tied/two-distinct/empty/negative | R-1 runs everywhere, asserted nowhere; refactor would silently change ranking |
| C-P0b | `qdrant_vector_store.append()` + dimension guard | sole streaming-write path, **0% tested**, home of I-1W |
| C-P0c | **metric parity**: `cli.direct_search_*` vs `EvaluationService._*` (incl. `::` ids) | the two already differ; pin before unifying (S-1a) |
| C-P0d | `experiment_runner` hypothesis-override branches | 38% unit cover; powers `eval --strategy` |

**Then (correctness of the product):**
- C-P1: RRF zero-score vector items (R-2); route weight-sum invariant `==1.0` (R-5, lives in
  data — invisible to coverage); parallel-embedding wrong-vector-count guard; streaming
  partial-write regression via `IndexingService` (I-1W end-to-end); eval edge cases (zero
  cases → metrics 0.0, `first_relevant_kind.none`); scanner/plugin id-dedup.
- Add `pytest.importorskip`/skip guards to inspection tests that need `rg`/`ctags`
  (currently silently binary-dependent). Fix the 2 unmarked `tests/unit/` files.

Target: keep ≥80% line coverage but ensure **every hot-path bug has an assertion** and the
core 3 commands have e2e coverage on the deterministic `hash`+`json` path.

---

## Workstream D — Bugs & stability (close on the core path)

From `AUDIT.md` + `AUDIT-2026-06-02.md`, the items that touch the *kept* core:

| Pri | ID | Fix |
|-----|----|-----|
| 🔴 | **I-1W** | Make streaming indexing transactional: stage → atomic swap; on any block failure abort without destroying the prior collection; refuse search on a partial collection. (Mostly fixed already via staging in qdrant store — **verify** `IndexingService` path and add C-P1 test.) |
| 🟠 | **R-8 / A-1** | Replace silent fallbacks with an explicit `degraded` flag + typed exceptions + debug re-raise. Fail-fast is a stated principle; a benchmarking tool must not report confident-wrong numbers. |
| 🟠 | **I-1 / I-10** | Honor `EMBEDDING_RETRY_ATTEMPTS` + partial-save in `ParallelEmbeddingService`/`IndexingService`. |
| 🟡 | **R-1/R-2/R-4/R-5/R-6/R-7** | Pin the **scoring contract** (normalization scheme, weight-sum invariant, BM25 variant, coverage denominator) with the C-P0a/C-P1 golden tests, then fix. |
| 🟡 | **D-1, J-1** | Warn when `line_chunks=false`+`structural_chunks=true`; fix JVM method regex false symbols. |

Most 🟠/🟡 fail-silent findings in `agent/`/`orchestration/` (AG-1/2/3, P-1/3, A-9) **leave the
trusted path automatically** once those packages move to `[research]` — fix them there only if
the research entrypoint is actively used.

---

## Sequenced roadmap (safe ordering)

```
Phase 0 — Characterization tests (C-P0a..d) ............ lock current behavior, no code change
Phase 1 — CLI deprecate: add index/search/eval flags, warn on the 12 .. user-facing target lands
Phase 2 — Extract eval engine + factories from cli.py (S-1, S-1a); unify metrics .. cli.py → ~250 LOC
Phase 3 — Promote VectorStore Protocol + break layering edges (S-5b/c/d) .. unblocks removal
Phase 4 — Move agent/orchestration/ai_indexing/pi/plugins/metrics → [research] extra; remove 12 cmds
Phase 5 — Fix core bugs (I-1W verify, R-8/A-1 degraded-flag, I-1 retry, scoring contract) + C-P1 tests
Phase 6 — Consolidate fragmentation (S-3), unify tracing + logging (4.1/4.4), fold RetrievalService
```
Each phase is independently shippable and leaves tests green. Phase 0 is the gate — nothing
moves until current behavior is pinned.

## Definition of done

- CLI is exactly `{index, search, eval}`; `--help` shows three commands; removed commands
  print a helpful pointer.
- `cli.py` is pure argparse + dispatch (~250 LOC); no metric/factory/business logic.
- One metric implementation; `eval` and any research eval share it.
- `VectorStore`/`GenerationProvider` contracts are Protocols; no `getattr`/`hasattr` probing.
- No silent fallbacks on the core path; failures surface (`degraded`/exception).
- Streaming indexing is transactional (no partial collections).
- Every hot-path bug (R-1, R-2, R-5, I-1W, metric parity) has an assertion; deterministic
  hash+json e2e covers index→search→eval.
- Research scaffolding (agent/orchestration/ai_indexing/pi/plugins/metrics) lives behind
  `code-diver[research]`, out of the trusted path.

## Source detail
Architecture findings S-1…S-5 + lean layout + keep/delete table; coverage map + P0/P1 test
plan; CLI disposition + before/after argparse + phased rollout — all captured in the three
sub-audits delegated for this plan. Bug IDs cross-reference `docs/spec/AUDIT.md` and
`docs/spec/AUDIT-2026-06-02.md`.
