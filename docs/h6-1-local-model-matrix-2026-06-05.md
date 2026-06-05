# H6.1 Local Model Matrix

Updated: 2026-06-05.

## Goal

Run 100-case local-model experiments without mixing variables.

The product target is an answer agent:

```text
user question
-> H6.1 calibrated hybrid file search over EmbeddingGemma-300M file metadata
-> LLM reranks candidate files
-> answer agent uses outline/symbol/rg/grep/read over those files
-> final code explanation / answer with evidence
```

Explanation and AI-judge experiments use CodeXGLUE code-to-text because H6.1 is a
code-search setup, not an end-to-end answer-agent benchmark. These results must
be reported in a separate section.

There are three evaluation stages:

1. **Find the right code.** Measured on CodeSearchNet retrieval with H6.1.
2. **Rank candidate files.** Measured by freezing H6.1 candidates and changing
   only the LLM reranker.
3. **Explain provided code.** Measured on CodeXGLUE code-to-text.

Do not average these metrics. A future full E2E benchmark can be generated with
our tools, but it should be explicitly marked `synthetic` until manually audited.

## Fixed Variables

| Axis | Value |
| --- | --- |
| Search dataset | `.code-diver/tmp/codesearchnet_python_100.jsonl` |
| Search cases | `100` |
| Search index | `.code-diver/benchmarks/mteb-codesearchnet-python/index-h5-embeddinggemma-300m-quality.json` |
| Embedding model | `google/embeddinggemma-300m` |
| Candidate generator | H6.1 static/grid hybrid weights |
| Retrieval top-k | `10` |
| Answer-agent tools | `code_diver_h3_search`, outline/symbol/rg/grep/read, rerank |
| Explanation dataset | CodeXGLUE code-to-text Python |
| Judge prompt | `prompts/code-explanation-judge.md` |

## Local Runtime Ports

| Model | Role candidates | Endpoint | Status |
| --- | --- | --- | --- |
| Gemma 4 E2B 4-bit | orchestrator, reranker, explainer, judge | `http://127.0.0.1:8012/v1/chat/completions` | Running |
| Gemma 4 E4B 4-bit | orchestrator, reranker, explainer, judge | `http://127.0.0.1:8013/v1/chat/completions` | Running |
| Qwen3.5 9B MLX 4-bit | cross-family AI judge | `http://127.0.0.1:8014/v1/chat/completions` | Running |
| Gemma 4 E4B OptiQ 4-bit | rejected runtime | `8013` attempted | Failed startup in `mlx_vlm.server` with missing vision-tower parameters |

## Validity Gates

Every run must record:

| Gate | Requirement |
| --- | --- |
| `completed_cases` | Equals planned cases unless explicitly marked partial. |
| `error_count` | `0` for valid quality comparisons. |
| JSON contract | All model outputs parse into the expected schema. |
| Degraded cases | Count and reason must be reported. |
| Model identity | Report must contain provider, model, endpoint, and config path. |
| Runtime | Mean and p95 latency must be reported. |
| Token usage | Input/output/total tokens when available. |
| Cost | Local runs use `$0` direct API cost; still report estimated local token volume. |
| Long-run persistence | Runs above 10 cases should write partial progress before each case or at least every N cases. |

## Search / Reranker Matrix

| ID | Changed variable | Config | Command | Output | Status |
| --- | --- | --- | --- | --- | --- |
| `SR-0` | No reranker, H6.1 static baseline | `configs/benchmarks/codesearchnet-h6-embeddinggemma-reranker-100.yml` | `uv run code-diver --config configs/benchmarks/codesearchnet-h6-embeddinggemma-reranker-100.yml experiment --hypothesis h6_embeddinggemma_static --json` | `.code-diver/reports/h6-1-local-matrix-sr0-static-100.json` | complete |
| `SR-1` | Qwen3-Reranker 0.6B cross-encoder | same | `uv run code-diver --config configs/benchmarks/codesearchnet-h6-embeddinggemma-reranker-100.yml experiment --hypothesis h6_embeddinggemma_qwen3_reranker_0_6b --json` | `.code-diver/reports/h6-1-local-matrix-sr1-qwen3-reranker-100.json` | queued; requires llama.cpp rerank server |
| `SR-2` | Gemma 4 E2B listwise reranker | to be split from agent config | `evaluate-search-tools --cases 100 --hypothesis agent_gemma4_e2b_local_rerank` | `.code-diver/reports/h6-1-local-matrix-sr2-gemma-e2b-rerank-100.json` | queued |
| `SR-3` | Gemma 4 E4B listwise reranker | needs E4B endpoint fix to `8013` | `evaluate-search-tools --cases 100 --hypothesis agent_gemma4_e4b_local_rerank` | `.code-diver/reports/h6-1-local-matrix-sr3-gemma-e4b-rerank-100.json` | config patch required |

## Search-Planning / Answer-Agent Tool Matrix

These runs are not the final answer quality metric. They measure the pre-answer
tool loop that searches/reranks candidate files before the model writes the final
code explanation.

| ID | Tool-loop model | Reranker model | Config | Command | Output | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `OR-1` | Gemma 4 E2B 4-bit | Gemini Lite | `configs/benchmarks/codesearchnet-agent-axis-embeddinggemma-100.yml` | `uv run code-diver --config configs/benchmarks/codesearchnet-agent-axis-embeddinggemma-100.yml evaluate-search-tools --cases 100 --workers 2 --hypothesis agent_gemma4_e2b_rerank_gemini_lite --json` | `.code-diver/reports/h6-1-local-matrix-or1-e2b-agent-gemini-rerank-100.json` | queued |
| `OR-2` | Gemma 4 E4B 4-bit | Gemini Lite | patched endpoint `8013` | `uv run code-diver --config <patched> evaluate-search-tools --cases 100 --workers 2 --hypothesis agent_gemma4_e4b_rerank_gemini_lite --json` | `.code-diver/reports/h6-1-local-matrix-or2-e4b-agent-gemini-rerank-100.json` | config patch required |
| `OR-3` | Gemma 4 E2B 4-bit | Gemma 4 E2B 4-bit | `configs/benchmarks/codesearchnet-agent-axis-local-100.yml` | `uv run code-diver --config configs/benchmarks/codesearchnet-agent-axis-local-100.yml --help-all evaluate-search-tools --cases 100 --workers 1 --hypothesis agent_gemma4_e2b_local_rerank --json` | `.code-diver/reports/local-agent-axis/local-agent-e2b-100.json` | complete; stable but rejected as primary search |
| `OR-4` | Gemma 4 E4B 4-bit | Gemma 4 E4B 4-bit | new local config | `evaluate-search-tools --cases 100 --workers 2 --hypothesis agent_gemma4_e4b_local_rerank` | `.code-diver/reports/h6-1-local-matrix-or4-e4b-agent-e4b-rerank-100.json` | config patch required |
| `OR-5` | Gemini 3.1 Flash Lite | Gemini 3.1 Flash Lite | `configs/benchmarks/codesearchnet-agent-axis-embeddinggemma-100.yml` | `uv run code-diver --config configs/benchmarks/codesearchnet-agent-axis-embeddinggemma-100.yml --help-all evaluate-search-tools --cases 100 --workers 1 --hypothesis agent_gemini_lite_rerank_gemini_lite --json` | `.code-diver/reports/local-agent-axis/gemini-lite-agent-rerank-100.json` | complete; better than local E2B, still below static H6.1 recall |

## Explanation / AI-Judge Matrix

| ID | Explanation model | Judge model | Dataset | Command | Output | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `EX-1` | Gemma 4 E2B 4-bit | Gemma 4 E4B 4-bit | CodeXGLUE code-to-text Python | `uv run code-diver --config configs/explanation-judge-gemma4-e2b.yml --help-all evaluate-explanations --cases 100 --yes --judge --judge-prompt prompts/code-explanation-judge.md --judge-config configs/explanation-judge-gemma4-e4b.yml --workers 4 --partial-output .code-diver/reports/h6-1-local-matrix-ex1-e2b-explain-e4b-judge-100.partial.json` | `.code-diver/reports/h6-1-local-matrix-ex1-e2b-explain-e4b-judge-100.json` | complete; Gemma-family judge |
| `EX-2` | Gemma 4 E4B 4-bit | Gemma 4 E4B 4-bit | CodeXGLUE code-to-text Python | `uv run code-diver --config configs/explanation-judge-gemma4-e4b.yml --help-all evaluate-explanations --cases 100 --yes --judge --judge-prompt prompts/code-explanation-judge.md --judge-config configs/explanation-judge-gemma4-e4b.yml --workers 4 --partial-output .code-diver/reports/h6-1-local-matrix-ex2-e4b-explain-e4b-judge-100.partial.json` | `.code-diver/reports/h6-1-local-matrix-ex2-e4b-explain-e4b-judge-100.json` | complete |
| `EX-3` | Gemma 4 E2B 4-bit | Qwen3.5 9B MLX 4-bit | CodeXGLUE code-to-text Python | `uv run code-diver --config configs/explanation-judge-gemma4-e2b.yml --help-all evaluate-explanations --cases 100 --yes --judge --judge-prompt prompts/code-explanation-judge.md --judge-config configs/explanation-judge-qwen35-9b.yml --workers 4 --partial-output .code-diver/reports/h6-1-local-matrix-ex3-e2b-explain-qwen9b-judge-100.partial.json` | `.code-diver/reports/h6-1-local-matrix-ex3-e2b-explain-qwen9b-judge-100.json` | complete; cross-family judge |
| `EX-4` | Gemma 4 E4B 4-bit | Qwen3.5 9B MLX 4-bit | CodeXGLUE code-to-text Python | `uv run code-diver --config configs/explanation-judge-gemma4-e4b.yml --help-all evaluate-explanations --cases 100 --yes --judge --judge-prompt prompts/code-explanation-judge.md --judge-config configs/explanation-judge-qwen35-9b.yml --workers 4 --partial-output .code-diver/reports/h6-1-local-matrix-ex4-e4b-explain-qwen9b-judge-100.partial.json` | `.code-diver/reports/h6-1-local-matrix-ex4-e4b-explain-qwen9b-judge-100.json` | complete; cross-family judge |

## Current Protocol Notes

- `Gemma E4B OptiQ` is not a valid local runtime in the current `mlx_vlm.server` path.
- `Gemma E2B` can fail the strict JSON contract for explanation eval. The evaluator now captures raw malformed JSON per case and continues, so one bad case does not abort the full run.
- Earlier explanation gates accidentally used a 1-case local dataset because the benchmark had been prepared with `--cases 1`. The CLI now expands the local CodeXGLUE artifact when a later run requests more cases.
- The H6.1 agent configs currently need an E4B endpoint correction: E4B rows must use `8013`, not `8012`.
- Explanation and AI-judge quality cannot be merged into H6.1 retrieval metrics. They should be reported side by side, not averaged.
- `OR-3` is now a valid same-index 100-case local-only search-planning run. It
  proves Gemma E2B can execute the tool loop, but it strongly underperforms the
  deterministic H6.1 locator and is not a primary candidate-file search setup.
- `OR-5` is the current API search-planning control: Gemini 3.1 Flash Lite both
  plans and reranks. It is better than local E2B, but still loses top-k recall to
  static H6.1 on this file-level benchmark.
- `evaluate-explanations` now supports `--workers` and `--partial-output`; large runs should always write partial progress.
- Local models often return JSON-ish output. The evaluator and judge now strip fenced JSON and repair invalid backslash escapes before treating a case as malformed.
- Cross-family judge is required. Gemma-vs-Gemma can overfit to family style; Qwen3.5 9B judge is the first local cross-family control.
- Gemma 4 E2B is not viable as a strict structured explainer in the current prompt/output contract. It produced 72-76 malformed generations per 100 cases.
- Gemma 4 E4B is viable as an explainer, but still needs parse-level retry or a plain-text output mode because it produced 9 malformed generations per 100 cases.
- Qwen3.5 9B is useful as a cross-family judge. It scored E4B explanations higher than E4B self-judge, with similar judge-error count, but higher runtime.

## Search Results So Far

| ID | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | File Recall@10 | File MRR@10 | nDCG@10 | Precision@R | Mean ms | P95 ms | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SR-0` | 100 | 0.820 | 0.930 | 0.970 | 0.970 | 0.970 | 0.876 | 0.900 | 0.820 | 858 | 863 | Fixed H6.1 static baseline; no LLM rerank. |
| `OR-3` | 100 | 0.510 | 0.570 | 0.640 | 0.700 | 0.700 | 0.564 | 0.596 | 0.510 | 11,501 | 12,879 | Gemma E2B local search-planning loop + rerank; 406 model calls, 312 tool calls, 3.05M local tokens, degraded 0. Stable but rejects itself on quality and speed. |
| `OR-5` | 100 | 0.740 | 0.860 | 0.860 | 0.860 | 0.860 | 0.797 | 0.813 | 0.740 | 10,660 | 14,375 | Gemini 3.1 Flash Lite search-planning loop + rerank; 454 model calls, 330 tool calls, 2.51M tokens, estimated API cost `$0.70`, degraded 0. Better precision, worse recall than static H6.1. |

### Current Search Interpretation

The same-index 100-case comparison now says:

1. **H6.1 static remains the default.** It has the best Hit@1/3/5/10 and is
   around `0.86s/query`.
2. **Gemma 4 E2B is not good enough for the search-planning loop.** It is
   reliable and fully local, but it drops Hit@5 from `0.970` to `0.640` while
   increasing mean latency to `11.5s/query`.
3. **Gemini 3.1 Flash Lite is the better intelligence layer, but not as a free
   search-planning loop.** It improves Precision@10 (`0.277` vs static `0.147`) because it
   returns a narrower final set, but loses recall (`0.860` vs `0.970`). That makes
   it a candidate for hard-tail rerank or precision mode, not the default broad
   search path.

The end-to-end answer-agent branch is still open:

```text
reranked files
-> A: bounded outline/symbol/rg/grep/read
-> B: ephemeral syntax-aware code index inside candidate files
-> code explanation answer
```

## Explanation Results So Far

| ID | Explainer | Judge | Cases | Gen errors | Judge errors | Judge overall | Token F1 | Key-token F1 | Bigram F1 | Duration min | Gen tokens | Judge tokens | Notes |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `EX-1` | Gemma 4 E2B 4-bit | Gemma 4 E4B 4-bit | 100 | 72 | 1 | 1.283 | 0.035 | 0.034 | 0.016 | 4.83 | 27116 | 58692 | Reject as structured explainer; too many malformed generations. |
| `EX-2` | Gemma 4 E4B 4-bit | Gemma 4 E4B 4-bit | 100 | 9 | 2 | 4.252 | 0.135 | 0.125 | 0.052 | 10.49 | 85320 | 190264 | Best local Gemma-only explanation setup so far. |
| `EX-3` | Gemma 4 E2B 4-bit | Qwen3.5 9B MLX 4-bit | 100 | 76 | 0 | 1.198 | 0.044 | 0.041 | 0.019 | 5.82 | 24609 | 52102 | Cross-family judge confirms E2B explainer rejection. |
| `EX-4` | Gemma 4 E4B 4-bit | Qwen3.5 9B MLX 4-bit | 100 | 9 | 2 | 4.430 | 0.137 | 0.127 | 0.054 | 15.83 | 84505 | 184980 | Best cross-family judged local explanation setup; slower than EX-2. |
