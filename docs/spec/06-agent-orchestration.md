# 06 — Agent Orchestration

Multi-round LLM agent loops that drive **read-only inspection tools** to either (a)
answer/locate code (`DirectSearchOrchestrator`) or (b) select what to index
(`DirectIndexingOrchestrator`). Used by `evaluate-search-tools` and `evaluate-indexing`.

Files: `agent/*`. Entry: `cli.py` `cmd_evaluate_search_tools` / `cmd_evaluate_indexing`.

## The loop contract

```
prompt ──▶ GenerationProvider ──▶ JSON {tool_calls | final}
                                       │
                       ParallelToolExecutor (≤ MAX_PARALLEL_TOOLS)
                                       │
                       DirectToolExecutor (tree/symbols/grep/rg/read/inspect)
                                       │
                       ToolObservationCompressor ──▶ history ──▶ next round
                                       (≤ MAX_ROUNDS, ≤ MAX_READ_CALLS)
```

| Component | Role |
|-----------|------|
| `direct_search_orchestrator.py` | Search loop. `MAX_ROUNDS=5`, `MAX_PARALLEL_TOOLS=6`, `MAX_READ_CALLS=10` |
| `direct_indexing_orchestrator.py` | Indexing loop. No read budget |
| `direct_tool_executor.py` | Runs tree/symbols/grep/rg/read/inspect against the repo |
| `parallel_tool_executor.py` | `asyncio.run` fan-out with a semaphore |
| `tool_manifest_builder.py` | Structured tool manifest (stage, parallel-safety, good/bad cases, args) |
| `tool_observation_compressor.py` | Shrinks verbose observations before re-feeding |
| `json_response_parser.py` | Extracts the action JSON from model output |
| `model_cost_estimator.py` | Token → USD estimate |
| `direct_agent_logger.py` | JSONL round/prompt/response/tool trace |

## Tools (read-only inspection)

`code_diver_tree`, `code_diver_symbols`, `code_diver_grep`, `code_diver_rg`,
`code_diver_read`, and `code_diver_inspect` (a batched multi-read).

**Contract (intended, fail-fast + sandboxed)**
1. Every path argument is confined to repo root (path guard, no `../`, no symlink escape).
2. Resource budgets are enforced and **cannot be bypassed**.
3. Tool errors are returned as structured results, programming errors are surfaced.

Resolved divergences:
- **(A-4) ✅ FIXED** `DirectToolExecutor` now validates **every** path arg through
  `PathGuard` at the executor boundary via `_validated_optional_path` /
  `_validated_required_path` — a `../../../etc/passwd` from model output or repo-file
  prompt-injection is rejected before touching the FS. (Was: paths passed directly with
  no guard.)
- **(A-3 / A-8) ✅ FIXED** `code_diver_inspect.reads[]` now counts each entry against
  `max_inspect_reads` (default 10); an oversized inspect returns a structured
  budget-error instead of silently bypassing the read budget. (Was: a multi-read inspect
  counted as one call, and `DirectIndexingOrchestrator` had no read budget at all.)

## Rerank tool — `code_diver_rerank` + `RerankToolHandler`

A new agent tool (commit `65461cd`) lets the search loop ask the model to reorder its
own candidate bank.

- `RerankToolHandler` wraps the generation provider and dedups a candidate bank (last 200
  candidates seen across the loop).
- Modes: `file_first`, `base_rank_prior`, `precision`, `compact`. Optional `reasons` +
  `confidence` in the response.
- `DirectSearchOrchestrator` can **force** a rerank call via `_should_force_rerank()`.

⚠️ Eval finding: the orchestrator tool path is **architecturally correct but NOT
production-ready** — 10.47 s latency, $0.415 / 100 queries, Hit@10 0.85 (worse than the
bounded deterministic Flash-Lite rerank at 2.2–3.3 s; see
[08](./08-evaluation-and-experiments.md)).

## Error handling

⚠️ **(A-1, High)** Both orchestrators wrap the loop in a blanket `except Exception` that
stores `str(exc)` on the result and returns normally — stack traces are discarded and a
genuine programming bug (AttributeError/KeyError) is indistinguishable from a transient
network failure. Reasonable for a *harness* (one case shouldn't abort the run) but there
is no debug re-raise or exception-type narrowing. The same pattern weakens
`query_plan_orchestrator.py` / `index_plan_orchestrator.py` for single operations
(⚠️ 4.3).

## Concurrency

⚠️ **(A-2, Medium)** `ParallelToolExecutor.execute` calls `asyncio.run()` — raises
`RuntimeError: event loop already running` if invoked inside an existing loop (Jupyter,
async host, async test runner). No `run_until_complete` fallback. Works in the CLI today.

## Response parsing

`json_response_parser.py` scans for embedded `{...}` and returns the **first** object
containing an action key.
⚠️ **(A-5, Medium)** A model that emits a JSON fragment in its scratchpad before the
real answer yields a spurious early match. Robust contract: take the last/top-level
action object.

## Cost & tokens

`model_cost_estimator.py` maps a model prefix → hardcoded price; unknown models fall to a
`$1.50/$9.00` default (A-7). When the provider returns 0 tokens, the orchestrator
substitutes a `len(text)//4` estimate (A-6) — inaccurate, duplicated in both
orchestrators, and triggered by the falsy-`0` check.

## Observation compression

⚠️ **(A-9, Medium)** `ToolObservationCompressor.compress` unconditionally
`result.pop("matches", None)` — strips grep/rg match lines from history. The model loses
sight of what was already found and re-issues redundant queries.

## Orchestration invariants (intended vs actual)

| # | Intended | Status |
|---|----------|--------|
| 1 | All file access confined to root | ✅ FIXED — PathGuard at DirectToolExecutor boundary (was A-4) |
| 2 | Read/round budgets unbypassable | ✅ FIXED — inspect.reads[] counted vs max_inspect_reads (was A-3, A-8) |
| 3 | Programming errors surfaced | ❌ A-1 |
| 4 | Works in sync + async hosts | ❌ A-2 |
| 5 | Action parse is robust to scratchpad text | ⚠️ A-5 |
| 6 | Cost/token accounting accurate | ⚠️ A-6, A-7 |
| 7 | History preserves load-bearing match data | ❌ A-9 |
