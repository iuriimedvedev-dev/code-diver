# Orchestrator Tool Log Analysis - 2026-05-31

This report covers the interrupted live `evaluate-search-tools` run `a9b42c820a02`, the read-only Claude Code audit, and the billing/provider follow-up.

## Run Status

Command:

```text
uv run code-diver --config configs/protogen-ollama-qdrant.yml evaluate-search-tools --dataset datasets/protogen_eval.jsonl --hypothesis ai_search_hybrid_orchestrator --hypothesis ai_search_vector_only --hypothesis ai_search_vector_rg --hypothesis ai_search_vector_symbols --hypothesis ai_search_vector_inspect --hypothesis ai_search_rg_only --hypothesis ai_search_grep_only --hypothesis ai_search_symbols_only --hypothesis ai_search_tree_only --hypothesis ai_search_inspect_only --json
```

The run was stopped deliberately after confirming it was still using standalone Gemini API billing through the default direct `generation` provider. The process exited with code `143`.

Trace files written before stop:

| Hypothesis | Trace | State |
| --- | --- | --- |
| `ai_search_vector_only` | `.code-diver/traces/orchestrator-search/a9b42c820a02/ai_search_vector_only.jsonl` | Completed 9 cases, 1 started but no final completion event before interruption. |
| `ai_search_rg_only` | `.code-diver/traces/orchestrator-search/a9b42c820a02/ai_search_rg_only.jsonl` | Completed 6 cases, 2 failed, 2 incomplete/no results. |
| `ai_search_grep_only` | `.code-diver/traces/orchestrator-search/a9b42c820a02/ai_search_grep_only.jsonl` | Completed 4 cases, 5 failed, 1 incomplete/no results. |
| `ai_search_symbols_only` | `.code-diver/traces/orchestrator-search/a9b42c820a02/ai_search_symbols_only.jsonl` | Interrupted during the first case. |

Because the run is partial, treat these numbers as diagnostic evidence about tool behavior, not a leaderboard.

## Tool Behavior

| Hypothesis | Cases seen | Completed with results | Failed | Hits on seen cases | Tool calls | Tool result volume |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ai_search_vector_only` | 10 | 9 | 0 | 9/10 | 11 `code_diver_search` | 29.9 KiB |
| `ai_search_rg_only` | 10 | 6 | 2 | 4/10 | 47 `code_diver_rg` | 166.5 KiB |
| `ai_search_grep_only` | 10 | 4 | 5 | 4/10 | 87 `code_diver_grep` | 263.6 KiB |
| `ai_search_symbols_only` | 1 | 0 | 0 | 0/1 | 1 `code_diver_symbols` | interrupted before result |

The pattern is still clear: raw lexical tools cause the model to loop. `grep_only` made 87 tool calls on a 10-case smoke run and failed 5 cases with `max_rounds_exceeded`. `rg_only` was better but still spent more tool calls and bytes for lower quality than `vector_only`.

`vector_only` is currently the strongest agent-facing tool surface because `code_diver_search` already returns ranked structured candidates with file paths, line ranges, scores, and `indexKind`. The model usually needs one search call plus one final JSON response.

## Failure Cases

`ai_search_grep_only` failed with `max_rounds_exceeded` on:

- `protogen-openrouter-settings`
- `protogen-pipeline-service-metrics`
- `protogen-arena-service`
- `protogen-cli-entrypoint`
- `protogen-eval-yaml`

`ai_search_rg_only` failed with `max_rounds_exceeded` on:

- `protogen-arena-service`
- `protogen-eval-yaml`

The common failure mode is not tool execution failure. It is planning failure: the model keeps trying new anchors instead of deciding from partial structured evidence. This supports keeping `grep` and `rg` as secondary probes, not first-stage discovery for informal questions.

## Spend Estimate

The interrupted run emitted 87 `model_usage` events before stop:

| Source | Input tokens | Output tokens | Total tokens | Estimated cost |
| --- | ---: | ---: | ---: | ---: |
| Gemini direct eval events before stop | 210,093 | 20,660 | 239,232 | $0.429029 after correcting `gemini-3-flash-preview` pricing |
| Claude Code read-only audit | n/a | n/a | n/a | $3.08371875 reported by Claude CLI |

The estimate is based on local model usage events and `ModelCostEstimator`; it is not a provider invoice. Google Cloud billing and ADC token checks failed with reauthentication errors in non-interactive shell.

## Billing Finding

`configs/protogen-ollama-qdrant.yml` previously did not define a `generation:` section. Direct evals therefore used `Defaults.GENERATION_PROVIDER`, which is `gemini`, not Pi and not Vertex. That means direct orchestrator runs used the standalone Gemini Developer API client with the AI Studio API key.

The config now explicitly sets:

```yaml
generation:
  provider: vertex
  model: gemini-3.5-flash
  fallback_models:
    - gemini-3-flash-preview
    - gemini-2.5-flash
  project: "236777862453"
  location: global
```

The Vertex smoke call is blocked until ADC reauthentication completes:

```text
Reauthentication is needed. Please run `gcloud auth application-default login` to reauthenticate.
```

## Claude Code Audit

Claude Code CLI was run read-only with `claude-opus-4-8` and no edit/write tools.

Metadata:

| Field | Value |
| --- | --- |
| CLI | Claude Code 2.1.112 |
| Model | `claude-opus-4-8` |
| Duration | 253.6s |
| Turns | 5 |
| Reported cost | $3.08371875 |
| Terminal reason | completed |

Highest-value findings:

1. `ParallelToolExecutor` was fail-fast because `asyncio.gather` used the default exception behavior. A single tool exception could abort the entire multi-tool batch and make hybrid hypotheses look worse than they are.
2. The executor has no per-tool timeout yet, so latency is bounded by the slowest tool in a round.
3. The current 100-case protogen dataset is not enough to claim stable wins across many tuned hypotheses; we need train/validation/test split and a second repo.
4. Token/cost accounting is only complete for LLM orchestrator paths; deterministic retrieval still needs explicit embedding-call and retrieval-cost logging.
5. Raw tool overuse is already visible in old and current traces.

Applied immediately:

- `ParallelToolExecutor` now catches per-tool exceptions and returns a failed `ToolResult`, preserving successful results from the same parallel batch.
- `configs/protogen-ollama-qdrant.yml` now routes direct generation through Vertex.
- `ModelCostEstimator` now uses explicit `gemini-3-flash-preview` pricing.

Verification:

- `uv run pytest -q`: `96 passed in 12.33s`

## Next Tests

After ADC is reauthenticated:

1. Run one-case Vertex smoke for `ai_search_vector_only`.
2. Run `ai_search_hybrid_orchestrator` on the 10-case smoke dataset through Vertex.
3. Compare it against `ai_search_vector_only`, `ai_search_vector_rg`, and `ai_search_vector_symbols`.
4. Add per-tool timeout and aggregate observation-byte caps, then rerun the same four hypotheses.
5. Promote only tools that improve `hit@1`, `file_mrr@10`, or `file_recall@10` without increasing tokens by more than 2x.

## Vertex Follow-Up

ADC was reauthenticated and the Vertex smoke call passed:

| Field | Value |
| --- | --- |
| Provider | `vertex` |
| Model | `gemini-3.5-flash` |
| Smoke tokens | 267 |
| Response | `{"ok": true, "provider": "vertex"}` |

Two Vertex eval runs were then executed with `--limit 3`. Note: this CLI flag is the retrieval top-k limit, not the number of dataset cases, so each run evaluated all 10 smoke cases.

| Run | Hypothesis | Hit@3 | MRR@3 | Hit@1 | File precision@R | File recall@3 | Tokens | Cost estimate | Mean latency | p95 latency | Errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `eaf6aa475627` | `ai_search_hybrid_orchestrator` | 0.800 | 0.800 | 0.800 | 0.767 | 0.717 | 152,829 | $0.264673 | 9.96s | 26.38s | 1 |
| `c9b8af50d28d` | `ai_search_vector_only` | 0.600 | 0.533 | 0.500 | 0.467 | 0.517 | 37,292 | $0.083033 | 4.14s | 5.45s | 3 |

The full hybrid result is the first live orchestrator run in this dataset where extra tools clearly improved quality over vector-only. The cost is still too high: 4.1x tokens and 2.4x mean latency versus vector-only.

Tool usage for `eaf6aa475627`:

| Tool | Calls | Result volume |
| --- | ---: | ---: |
| `code_diver_search` | 16 | 40.7 KiB |
| `code_diver_read` | 20 | 73.7 KiB |
| `code_diver_tree` | 4 | 29.9 KiB |
| `code_diver_grep` | 5 | 5.4 KiB |
| `code_diver_rg` | 2 | 2.3 KiB |
| `code_diver_symbols` | 1 | 6.6 KiB |

The symbols guard worked: after rejecting broad symbols when vector search is available, the completed full hybrid run used only one scoped symbols call (`path: src/sessions/service.py`). The new dominant cost driver is `code_diver_read`: 20 reads on 10 cases.

Case notes for the full hybrid run:

- Strong wins: `arena`, `cli`, `eval-yaml`, `openrouter`, `pipeline`, `session`, `frontend`, and `fastapi` were found at rank 1.
- Misses: `docker-compose` returned `docker-compose.yml`, while the dataset expects `docker-compose.dev.yml` or `docker-compose.monitoring.yml`; `metrics-collector` read relevant-looking files but returned no final result.
- Most high-latency cases used 4-5 model rounds. This should be capped by prompt and by evaluator budgets.

Immediate implementation follow-up from this run:

- `code_diver_symbols` without `path` is now rejected when `code_diver_search` is available, preventing accidental full-repo symbol scans inside hybrid search.
- The prompt now explicitly says never to call `code_diver_symbols` without a path when vector search is available.
- `code_diver_read` now has a hard runtime budget of 10 calls per case. Extra read calls return a structured `read_budget_exceeded` tool result instead of reading more source.
- The prompt now tells the agent to use the intended flow: `code_diver_search` for candidates, `grep`/`rg` or scoped symbols for fast verification, and small targeted `read` ranges only for final evidence.
- Next guard should cap total observation bytes per round and prefer at most 3 reads by prompt unless the query names exact files.

## Full 100-Case Vertex Eval

Run `66fa11b0e393` evaluated the four main agent-tool hypotheses on `datasets/protogen_eval_100.jsonl` through Vertex `gemini-3.5-flash`.

Command:

```text
uv run code-diver --config configs/protogen-ollama-qdrant.yml evaluate-search-tools --hypothesis ai_search_hybrid_orchestrator --hypothesis ai_search_vector_only --hypothesis ai_search_vector_rg --hypothesis ai_search_vector_symbols --json
```

### Summary

| Hypothesis | Hit@10 | MRR@10 | Hit@1 | File precision@R | File recall@10 | nDCG@10 | MAP@10 | Tokens | Cost | Mean latency | p95 latency | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ai_search_vector_only` | 0.800 | 0.748 | 0.700 | 0.580 | 0.655 | 0.653 | 0.609 | 455,876 | $0.961 | 5.13s | 10.03s | 11 |
| `ai_search_vector_symbols` | 0.740 | 0.710 | 0.680 | 0.570 | 0.605 | 0.616 | 0.578 | 735,696 | $1.423 | 6.44s | 10.40s | 17 |
| `ai_search_hybrid_orchestrator` | 0.650 | 0.645 | 0.640 | 0.505 | 0.510 | 0.538 | 0.505 | 1,427,533 | $2.481 | 8.97s | 24.62s | 26 |
| `ai_search_vector_rg` | 0.600 | 0.567 | 0.540 | 0.465 | 0.510 | 0.509 | 0.481 | 786,935 | $1.499 | 7.95s | 16.07s | 35 |

Full-run conclusion: exposing more tools directly to the model does not improve the 100-case benchmark. `ai_search_vector_only` is still the best agent-facing baseline. `ai_search_vector_symbols` is the least bad multi-tool variant: it is close on quality but costs 1.6x tokens and has more errors. `ai_search_vector_rg` and the full hybrid toolset both degrade quality and reliability.

### Tool Use

| Hypothesis | Tool calls | Result volume notes |
| --- | ---: | --- |
| `ai_search_vector_only` | 120 `code_diver_search` | 338.9 KiB search observations. |
| `ai_search_vector_symbols` | 118 `code_diver_search`, 92 `code_diver_symbols` | 332.9 KiB search + 464.2 KiB symbols. |
| `ai_search_vector_rg` | 117 `code_diver_search`, 228 `code_diver_rg` | 322.3 KiB search + 510.7 KiB rg. |
| `ai_search_hybrid_orchestrator` | 122 search, 192 read, 32 grep, 26 rg, 17 symbols, 15 tree | 1.38 MiB structured observations; reads were the largest source at 649.5 KiB. |

The read budget worked: the full hybrid run never exceeded 5 `code_diver_read` calls in a case, so the hard limit of 10 was not hit. The problem is not runaway reading anymore. The remaining failure mode is decision paralysis: the model keeps verifying and then either reaches `max_rounds_exceeded` or returns no final result.

### Error Pattern

| Hypothesis | `max_rounds_exceeded` | No tool calls/results | Other |
| --- | ---: | ---: | ---: |
| `ai_search_vector_only` | 4 | 7 | 0 |
| `ai_search_vector_symbols` | 5 | 12 | 0 |
| `ai_search_vector_rg` | 26 | 9 | 0 |
| `ai_search_hybrid_orchestrator` | 13 | 13 | 1 read path error |

The `rg` tool is especially risky as an agent-facing primitive. It gives the model too many opportunities to invent another regex instead of finalizing. Symbols are safer, but still produce enough extra context and turns to lose against plain `code_diver_search`.

### Case-Level Pattern

The full hybrid did improve some individual cases over vector-only:

- `where-agent-factory`
- `where-api-prompts`
- `where-arena-aggregation`
- `where-database-session`
- `where-direct-agents`
- `where-eval-import`
- `where-frontend-prompts`
- `where-platform-tools`
- `where-prompt-templates`
- `where-settings-api`

But it also lost many cases that vector-only solved at rank 1, including operator/config/session/strategy cases such as `where-ailoop`, `where-claude-operator`, `where-gemini-operator`, `where-openai-operator`, `where-session-starts`, and `where-strategy-created`. The tools are useful, but letting the model decide an open-ended multi-round plan is too unstable.

### Next Hypotheses

The next promising direction is not "more agent tools"; it is deterministic hybrid candidate generation plus a bounded model step:

1. Keep `code_diver_search` as the primary agent-facing tool.
2. Move `symbols`, `rg`, `grep`, and tree/path checks below the agent boundary as deterministic reranking features.
3. Add a strict one-shot finalizer/reranker prompt over a compact candidate table, not a multi-round tool loop.
4. Add a "must finalize after candidate evidence" rule for direct search: after a successful `code_diver_search` result and one optional verification round, require final JSON results.
5. Route path/config/package/docker queries deterministically; the full hybrid missed path-ish cases like `where-dev-compose` and `where-sample-apps` despite having tree/grep/read.

## One-Shot Hybrid LLM Rerank

Run `2714426c462a4d54baad12aadc39b517` evaluated `hybrid_candidates_llm_rerank` on the full 100-case `datasets/protogen_eval_100.jsonl` suite. This is the first bounded version of the "hybrid candidate generation plus AI finalizer" idea:

- Candidate generation is deterministic: vector, lexical/BM25, path, symbol, and AST graph features produce up to 40 candidates.
- Gemini/Vertex receives a compact candidate table and must return JSON indices only.
- There is no multi-round tool loop, no source reads, and no open-ended grep/rg/symbol probing.
- Full prompt/response/token/cost logs are recorded as `llm_rerank_prompt` and `llm_rerank_response` trace events.

Command:

```text
uv run code-diver --config configs/protogen-ollama-qdrant.yml experiment --hypothesis hybrid_candidates_llm_rerank --json
```

### Result

| Hypothesis | Hit@10 | MRR@10 | Hit@1 | Hit@3 | Precision@10 | Recall@10 | File precision@R | File recall@10 | nDCG@10 | MAP@10 | Tokens | Cost | Mean latency | p95 latency | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_candidates_llm_rerank` | 0.930 | 0.795 | 0.270 | 0.580 | 0.517 | 0.920 | 0.620 | 0.800 | 0.743 | 0.682 | 1,192,817 | $2.051 | 4.38s | 6.13s | 0 |
| `ai_search_vector_only` | 0.800 | 0.748 | 0.700 | 0.800 | 0.498 | 0.655 | 0.580 | 0.655 | 0.653 | 0.609 | 455,876 | $0.961 | 5.13s | 10.03s | 11 |
| `ai_search_hybrid_orchestrator` | 0.650 | 0.645 | 0.640 | 0.650 | 0.552 | 0.510 | 0.505 | 0.510 | 0.538 | 0.505 | 1,427,533 | $2.481 | 8.97s | 24.62s | 26 |

The bounded reranker is the best quality result so far by `hit@10`, `MRR@10`, `recall@10`, `file_recall@10`, `nDCG@10`, and `MAP@10`. It also removes the direct-agent failure class: no `max_rounds_exceeded`, no malformed tool calls, and no empty final answers in this run.

Follow-up on 2026-06-01 found a metrics bug in `hit@1`/`hit@3`: symbol ids such as `src/file.py::Class#hash` were not matched against expected file paths. After fixing the matcher, the corrected baseline is `hit@1=0.70`, `hit@3=0.87`, `MRR@10=0.785`, `nDCG@10=0.735`, and `MAP@10=0.673`. The reranker is therefore a real ranking improvement, not a rank-one regression.

The remaining weakness is exact first-result ownership. The model often chooses the right file family, but can still put an adjacent model, wrapper, or prompt file above the most direct implementation file.

### Usage

Trace summary for the 100 `llm_rerank_response` events:

| Metric | Value |
| --- | ---: |
| Model calls | 100 |
| Input tokens | 1,120,631 |
| Output tokens | 41,118 |
| Total tokens | 1,192,817 |
| Estimated cost | $2.051 |
| Mean model latency | 4.18s |
| p95 model latency | 6.22s |
| Model | `gemini-3.5-flash` |

The cost is lower than the open-ended hybrid agent loop, but still more than 2x `ai_search_vector_only`. Most of that cost is prompt-side: 40 candidates with previews produce large prompts. The next optimization should be adaptive candidate compression, not another open tool loop.

### Bucket Pattern

| Bucket | Cases | Hit@10 | Hit@1 | Hit@3 | File precision@R | File recall@10 | nDCG@10 | MAP@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `path_symbol` | 31 | 0.935 | 0.452 | 0.742 | 0.710 | 0.806 | 0.784 | 0.736 |
| `semantic` | 30 | 0.900 | 0.100 | 0.500 | 0.550 | 0.817 | 0.708 | 0.641 |
| `workflow` | 39 | 0.949 | 0.256 | 0.513 | 0.603 | 0.782 | 0.737 | 0.671 |

The reranker works best on path/symbol cases and worst on semantic rank-one selection. That matches the trace behavior: when path/title/symbol names are strong, the model can select useful candidates; when the query is purely informal, it preserves recall but struggles to identify the exact top answer.

### Next Optimization

This result changes the direction:

1. Keep the bounded reranker. It is clearly better than an open-ended agent tool loop.
2. Add adaptive candidate tables: 15-20 candidates for confident deterministic results, 40 only for low-confidence/ambiguous queries.
3. Add file-level grouping before rerank. The reranker should first choose files, then choose best symbols/chunks inside selected files. This should improve `hit@1`.
4. Add deterministic first-rank protection: if the base vector/hybrid top result is very strong and path/symbol evidence agrees, pin it unless the reranker has high-confidence reason to move it.
5. Add a smaller "reason-free" rerank response schema for eval runs to reduce output tokens.
6. Parallelize `experiment` evaluation with bounded concurrency. Current wall-clock time is dominated by 100 sequential Vertex calls even though each call is independent.
