# Code Diver — Delta Audit: Observability/Tracing Batch (2026-06-02, batch T)

**Scope:** the 4 commits after `7751aaa` — `9b77199` (trace evaluation progress), `4265ee2`
(compact-locator docs + `monitor` command + `TraceMonitor` + `IndexCompositionAnalyzer`),
`9946474` (retrieval diagnostics + graph ablations), `a748ac4` (IntelliJ locator sweep doc).
Net: +399 LOC, 204 files, 181 tests (172 pass / 9 deselected, **no regressions**).
Companion to [`AUDIT.md`](./AUDIT.md) and [`AUDIT-2026-06-02.md`](./AUDIT-2026-06-02.md).
Only NEW findings listed (prefixed **T-**).

---

## Verdict

> This batch is **observability infrastructure**, not cleanup or bug-fixing. It's directionally
> useful (progress tracing, a live monitor, graph-ablation telemetry, compact-index validation)
> and the **graph-ablation refactor is a clean, behavior-preserving change** (verified pure
> telemetry — no retrieval regression). But it adds a cluster of **tracing-reliability bugs**,
> the most ironic being that **the observability layer can corrupt its own trace file** (T-5),
> and the planned cleanup/CLI-collapse and the standing fail-silent debt remain **untouched**.

The strategic note for the project owner: this is the **third consecutive batch that grows the
codebase (now 12.7k LOC, 16 CLI commands) while the lean `{index, search, eval}` target and the
open correctness debt move backwards.** Feature/observability velocity is high; convergence on
"clean, simple, stable" is not happening.

---

## New findings (ranked)

| # | Sev | ID | Finding | Location |
|---|-----|----|---------|----------|
| 1 | 🟡 Med | T-5 | **Two `TraceLogger` instances write the same file under separate locks.** `ExperimentRunner` and `HybridRetrievalStrategy` (via the factory) each construct `TraceLogger(config.trace)` for the same `artifact` path but with independent `threading.Lock`s. Under parallel workers, large `hybrid_rank_stages` appends (30–60 KB) exceed the atomic-append size and can **interleave into corrupt JSONL lines** that the monitor then silently drops. Extends finding 4.1. | `experiments/experiment_runner.py:52`, `strategies/retrieval_strategy_factory.py:63` |
| 2 | 🟡 Med | T-7 | **`TraceMonitor` never resets `_offset` after file truncation/rotation.** A restarted benchmark replaces the trace file; `seek(old_offset)` lands past the new EOF, so the monitor **silently freezes** showing no new events. Fix: detect `tell() < _offset` (file shrank) → reset to 0. | `ui/trace_monitor.py:33-46` |
| 3 | 🟡 Med | T-2 | **Parallel eval loses all partial results on any worker exception.** `future.result()` re-raises out of `evaluate()`; the `evaluation_completed` event is never written and every finished case is discarded. A transient failure at case 95/100 throws away the whole run. Add a `degraded_cases` counter + emit completion even on early exit. | `services/evaluation_service.py:59-64` |
| 4 | 🟡 Med | T-1 | **`_item_profiles` dict written from multiple worker threads with no lock.** The `_cache_lock` (RLock) added for `_lexical_index`/`_graph`/`_neighbor_index` was **not** extended to `_item_profiles`. Benign under the CPython GIL (frozen values, atomic dict ops) but structurally racy — breaks under free-threaded/alt runtimes; causes redundant profiling today. | `strategies/hybrid_candidate_scorer.py:48-52` |
| 5 | 🟡 Med | T-13 | **`monitor` starts on a stale/wrong file when `trace.enabled=false`** and no `--trace` given — user watches an old run's file with no indication tracing is off. | `cli.py:643-650` |
| 6 | 🟢 Low | T-3 | **`TraceLogger.write()` does `mkdir`+open+write+close per event.** With workers>1 and tracing on, ~one serialized critical section per query (60-row `json.dumps` under lock) — serializes the workers at trace-write time. Use a persistent handle. | `tracing/trace_logger.py:26-29` |
| 7 | 🟢 Low | T-4 | `_trace_rank_stages` runs 7 full sort passes over the candidate dict per query (trace-enabled only; eval configs set `enabled:true`). | `strategies/hybrid_retrieval_strategy.py:395-401` |
| 8 | 🟢 Low | T-6 | `ExperimentRunner` duration timer starts **after** strategy construction → lazy-init cost (graph/lexical load) excluded; cross-hypothesis `duration_ms` comparisons are biased (first hypothesis pays init, rest don't). | `experiments/experiment_runner.py:45,51` |
| 9 | 🟢 Low | T-11 | `graph_candidate_count` trace counts pre-None-filter items, over-reporting candidates actually merged. | `strategies/hybrid_retrieval_strategy.py:103` |
| 10 | 🟢 Low | T-8 / T-9 | `TraceMonitor.run()` has no clean-exit hook (untestable w/o mocking `sleep`); missing trace file shows a blank TUI with no "waiting for <path>" message. | `ui/trace_monitor.py:26-35` |

**Verified clean (no regression):** T-10 — the `_graph_scores(profile)` refactor is pure
telemetry; the externally-built `GraphExpansionProfile` equals what was computed inline, no
retrieval-behavior change, no KeyError risk in `final_graph_hits`. `IndexCompositionAnalyzer`
(T-12) is correct (division-by-zero guarded, empty-index → 0.0).

---

## Standing debt — status after this batch

| Prior finding | Status |
|---------------|--------|
| **4.1** two trace schemas | **slightly worsened** — schema is now consistent (`timestamp/event/payload`), but T-5 introduces two-lock contention on one file |
| **R-8 / A-1** degraded flag vs silent fallback | **untouched** (parallel path propagates exceptions, the right direction, but no `degraded` signal) |
| **R-1 / R-5** scoring contract + golden tests | **untouched** |
| **I-1 / I-10** embedding retry / partial-save | **untouched** |
| **S-1a** duplicate metric algebra in `cli.py` (859-988), cli copy missing `::` match | **untouched** — still 0% parity-tested |
| CLI collapse 15→3 (`{index,search,eval}`) | **regressed** — now **16** commands (`monitor` added); `cli.py` 1,100 → **1,129** |

## Remediation priority for this batch

1. **T-5 (Med):** one shared `TraceLogger` per `artifact` path (singleton/inject), not one per
   subsystem — eliminates the interleaved-write corruption. Pairs with the 4.1 unification.
2. **T-7 (Med):** reset `_offset=0` when the file shrank; show a "waiting for <path>" state.
3. **T-2 (Med):** capture per-case failures into a `degraded_cases` count and always emit
   `evaluation_completed` (ties into the R-8/A-1 `degraded` work).
4. **T-1 (Med):** extend `_cache_lock` to `_item_profiles` (or document the GIL dependency).
5. **T-13 / T-3 (Low):** guard `monitor` on `trace.enabled`; use a persistent file handle in
   `TraceLogger`.
