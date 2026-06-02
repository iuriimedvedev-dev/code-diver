# IntelliJ H2 Post-Ranking Benchmark

Date: 2026-06-02

## Goal

Compare two post-locator search scenarios across three orchestrator/ranker models.

The persistent index is intentionally fixed: a compact IntelliJ file-locator index using local Qwen embeddings in Qdrant. This benchmark is about what happens after likely files are found.

## Matrix

| ID | Scenario | Orchestrator / Ranker | Status |
| --- | --- | --- | --- |
| A1 | Locator -> outline/symbol/rg/grep/read -> rerank | Qwen3.5 4B local | Ran 10-case smoke |
| B1 | Locator -> ephemeral syntax-aware local vector search -> rerank | Qwen3.5 4B local | Ran 10-case smoke |
| A2 | Locator -> outline/symbol/rg/grep/read -> rerank | Gemini 3.1 Flash Lite via Vertex | Configured, not run |
| B2 | Locator -> ephemeral syntax-aware local vector search -> rerank | Gemini 3.1 Flash Lite via Vertex | Configured, not run |
| A3 | Locator -> outline/symbol/rg/grep/read -> rerank | Gemini 3.5 Flash via Vertex | Configured, not run |
| B3 | Locator -> ephemeral syntax-aware local vector search -> rerank | Gemini 3.5 Flash via Vertex | Configured, not run |

Vertex/Gemini runs are now active via Vertex AI after the user reauthorized `gcloud` and explicitly approved external model evaluation. The current target is strict: `Hit@10 >= 0.95` on the IntelliJ 1000-case dataset.

## Fixes Made Before The Valid Smoke

Two experiment-validity bugs were found during the first local attempts.

1. The prompt builder mentioned tools that were not available in a hypothesis. Branch B did not have `code_diver_read`, but the prompt still instructed the model about read usage, causing repeated `tool_not_allowed` loops.
2. Branch B only exposed `code_diver_ephemeral_search`; it did not enforce using it. The model could skip the scenario under test and go directly from locator to rerank/final answer.

The current code now:

- builds search prompts from the actual tool manifest;
- tells the model never to call absent tools;
- runtime-forces `code_diver_ephemeral_search` for hypotheses whose name contains `ephemeral`;
- fail-soft returns accumulated candidates with an error flag when the local model breaks JSON/tool protocol.

## Baseline

Same first 10 IntelliJ cases, deterministic file locator only:

| Run | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | File Recall@10 | MRR@10 | NDCG@10 | MAP@10 | Mean ms | P95 ms | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Local Qwen file locator | 0.20 | 0.50 | 0.60 | 0.60 | 0.060 | 0.60 | 0.60 | 0.370 | 0.428 | 0.370 | 80 | 468 | 0 |

This is the key control: the compact local locator already gets the answer into top 5/10 on 60% of this small sample, but rank 1 is weak.

## Main Local Smoke

Raw artifacts:

- `.code-diver/reports/intellij-postrank-h2-qwen-local-rerank-enforced-10.json`
- `.code-diver/reports/intellij-postrank-h2-qwen-local-rerank-enforced-10.html`
- `.code-diver/traces/orchestrator-search/8c4d91256799/`

| Run | Scenario | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | File Recall@10 | MRR@10 | NDCG@10 | MAP@10 | Mean ms | P95 ms | Errors | Model Calls | Tool Calls | Tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | grep/read/rerank | 0.40 | 0.50 | 0.60 | 0.60 | 0.125 | 0.60 | 0.60 | 0.470 | 0.502 | 0.470 | 23,001 | 46,528 | 7 | 29 | 17 | 104,577 |
| B1 | ephemeral/rerank | 0.40 | 0.50 | 0.60 | 0.60 | 0.125 | 0.60 | 0.60 | 0.470 | 0.502 | 0.470 | 15,011 | 28,056 | 9 | 26 | 16 | 83,366 |

95% CI on Hit@1 for both local runs: `0.168 .. 0.687`, width `0.519`. With only 10 cases, the confidence interval is huge; these numbers are useful as smoke diagnostics, not final quality claims.

## Tool Usage

| Run | Completed | Completed With Error | Actual Tool Calls | Fallbacks |
| --- | ---: | ---: | --- | --- |
| A1 | 10 | 7 | `search=10`, `rerank=4`, `outline=2`, `read=1` | `agent_protocol_error_last_candidates=7` |
| B1 | 10 | 9 | `search=12`, `ephemeral=3`, `rerank=1` | `agent_protocol_error_last_candidates=6`, `exception_last_candidates=3`, `max_rounds_last_candidates=1` |

Branch B only reached actual `code_diver_ephemeral_search` in 3 of 10 cases. The runtime enforcement works when the model returns parseable tool protocol, but local Qwen often returns invalid or incomplete JSON before the forced step can run.

## Readout

The local Qwen orchestrator did improve rank-1 on this sample versus the deterministic locator (`0.20 -> 0.40`), while preserving Hit@5/10. That means LLM ranking can help when the correct file is already in the locator candidate set.

The local Qwen orchestrator is not reliable enough for a 100-case agentic sweep yet. Error rates of 70-90% mean a larger run would mostly measure prompt/protocol brittleness, not the search strategy.

Branch B did not yet prove that localized ephemeral indexing improves quality. In the enforced smoke it matched Branch A on quality and was faster, but it only truly used ephemeral search in 3/10 cases. We need a deterministic scenario runner that executes the required tool sequence and uses the model only for ranking, or constrained JSON/tool calling for the local model.

## Next Step

For a fair 6-way comparison, the next runner should execute the scenario skeleton deterministically:

- A: locator top N -> selected outline/symbol/rg/read probes -> model rerank.
- B: locator top N -> forced ephemeral syntax-aware index/search -> model rerank.

Then the only model-variable part is ranking/orchestration choice, not whether the model remembered to call the required scenario tool. After that, run A/B for Qwen local, Gemini Flash Lite, and Gemini Flash on 100 cases, then promote the winner to 1000.

## Deterministic Runner Update

The deterministic H2 runner now exists as `scripts/run_postrank_h2_deterministic.py`.

It removes the model-controlled tool-protocol variable from this specific benchmark:

- Branch A is always `locator -> outline/symbol/rg probes -> rerank`.
- Branch B is always `locator -> ephemeral syntax-aware index over locator files -> rerank`.
- The model variable is only the final listwise ranker.
- Rerank has retry attempts and compact fallback prompts.
- Long runs write partial checkpoint JSON files under `.code-diver/reports/partials-*`.

This is the correct setup for comparing the post-locator hypotheses. The older agentic smoke above remains useful as a protocol reliability diagnostic, but not as a clean quality comparison.

## Infrastructure Fixes

The 1000-case run was blocked by three non-quality issues:

1. Qdrant container was running without published host ports. Recreating it with compose fixed `localhost:6333`.
2. `configs/intellij-postrank-h2.yml` pointed at an interrupted staging collection. It now points at stable `intellij_community_file_locator_local_qwen`.
3. The H2 config had drifted away from the file-locator hypothesis by enabling structural/symbol chunks while search weights targeted `file_summary`. It is back to one `file_summary` item per file.

The local Qwen locator index was rebuilt successfully:

| Metric | Value |
| --- | ---: |
| Collection | `intellij_community_file_locator_local_qwen` |
| Items | 74,906 |
| Item kind | `file_summary` |
| Unique paths | 74,906 |
| Content size | 172.95 MB |
| Embedding model | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` |
| Dimensions | 1024 |

## Gemini / Vertex Status

After `gcloud` reauth, a safe synthetic Vertex smoke succeeded for both target model IDs:

| Model ID | Smoke Status |
| --- | --- |
| `gemini-3.1-flash-lite` | OK |
| `gemini-3.5-flash` | OK |

The full Gemini eval is running through Vertex AI. Results are written incrementally to:

- `.code-diver/reports/partials-gemini-flash-lite-1000/`
- `.code-diver/reports/partials-gemini-flash-35-1000/`
- `.code-diver/reports/partials-h3-gemini-flash-lite-1000/`
- `.code-diver/reports/partials-h3-gemini-flash-35-1000/`
- `.code-diver/reports/partials-h4-gemini-flash-lite-1000/`
- `.code-diver/reports/partials-h4-gemini-flash-35-1000/`

The live matrix is summarized in `docs/intellij-h2-matrix-overnight-2026-06-02.md`.

## H3/H4 Update

Two additional branches were added after diagnosing the H2 miss pattern:

| Branch | Flow | Why it exists |
| --- | --- | --- |
| C | union of balanced, lexical-heavy, path/symbol, and vector-wide locator profiles -> probes -> rerank | Raise candidate recall without asking the LLM to invent new search terms. |
| D | LLM query planner + deterministic symbol hypotheses -> multi-query profile union -> probes -> rerank | Use the LLM before retrieval to generate likely class/method/search variants. |

The runner now records per-case diagnostics: `locator_rank`, `candidate_rank`, `rerank_rank`, `expected_sources`, and `query_variants`. This is necessary because aggregate `Hit@10` cannot tell whether we lost the file before retrieval, during candidate mixing, or during reranking.

The first concrete H4 smoke result fixed the known `ProjectManagerImpl.kt` miss:

| Case | Plain locator | H4 candidate rank | Final rank |
| --- | ---: | ---: | ---: |
| `where-project-open` | missing | 55 | 1 |

The fix required two candidate-construction changes:

- source-balanced mixing so `outline`, `symbols`, `rg`, and ephemeral chunks are not called and then sliced away;
- query-priority mixing so the original query keeps a wide quota while the first symbol-like variants also get guaranteed slots.

## Active 1000-Case Run

The currently valid local run is:

```bash
.venv/bin/python scripts/run_postrank_h2_deterministic.py \
  --cases 1000 \
  --progress-every 25 \
  --partial-dir .code-diver/reports/partials-qwen-1000 \
  --output .code-diver/reports/intellij-postrank-h2-deterministic-qwen-1000.json \
  --report .code-diver/reports/intellij-postrank-h2-deterministic-qwen-1000.html \
  --hypothesis h2a_grep_read_rerank_qwen35_4b \
  --hypothesis h2b_ephemeral_rerank_qwen35_4b
```

This run is local-only: Qdrant + local Qwen embeddings + local Qwen3.5 4B ranker.
