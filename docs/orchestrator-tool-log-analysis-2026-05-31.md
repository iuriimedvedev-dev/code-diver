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
- Next guard should cap verification reads, for example max 3 `code_diver_read` calls per case unless the query names exact files.
