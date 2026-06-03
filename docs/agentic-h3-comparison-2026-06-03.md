# Agentic H3 Comparison - 2026-06-03

This report records the first 100-case IntelliJ comparison of:

- **Pure H3:** deterministic H3 manifest-union retrieval plus Gemini 3.1 Flash Lite rerank.
- **Agentic H3:** Gemini 3.1 Flash Lite as the entry-point agent, with access to `code_diver_h3_search`, outline, symbols, grep, rg, read, and rerank tools.

Gemini 3.5 Flash is intentionally excluded from active testing here because it is too expensive for the current experiment loop.

## Artifacts

| Run | Artifact |
| --- | --- |
| Agentic H3, Gemini 3.1 Flash Lite | `.code-diver/reports/agentic-h3-100/intellij-agentic-h3-gemini-lite-100.json` |
| Pure H3, Gemini 3.1 Flash Lite | `.code-diver/reports/agentic-h3-100/intellij-pure-h3-gemini-lite-100.json` |
| Agentic H3 trace | `.code-diver/traces/orchestrator-search/4bcf24916bfc/ai_h3_agentic_gemini_flash_lite.jsonl` |

The abandoned Gemini 3.5 artifact is a zero-byte file and should not be used for conclusions:

```text
.code-diver/reports/agentic-h3-100/intellij-agentic-h3-gemini-35-100.json
```

## Results

| Strategy | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | File Recall@10 | nDCG@10 | MAP@10 | Mean ms | P95 ms | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pure H3 + Gemini Lite rerank | 100 | 0.76 | 0.97 | 0.97 | 1.00 | 0.939 | 0.159 | 0.919 | 0.847 | 0.796 | 12,719 | 16,748 | $0.220 |
| Agentic H3 + Gemini Lite | 100 | 0.56 | 0.75 | 0.78 | 0.80 | 0.748 | 0.209 | 0.724 | 0.654 | 0.611 | 14,630 | 20,038 | $0.866 |
| Agentic H3 bounded tools + Gemini Lite | 100 | 0.55 | 0.73 | 0.74 | 0.75 | 0.679 | 0.282 | 0.655 | 0.607 | 0.562 | 15,055 | 21,711 | $0.870 |
| Agentic H3 bounded tools + Qwen3.5 4B local | 100 | 0.65 | 0.79 | 0.81 | 0.85 | 0.777 | 0.145 | 0.771 | 0.701 | 0.654 | 44,570 | 52,690 | local |

## Tool Usage

Agentic H3 used substantially more LLM and tool calls than Pure H3.

| Metric | Agentic H3 | Pure H3 |
| --- | ---: | ---: |
| Model calls | 576 | 100 |
| Tool calls | 445 | 100 |
| Input tokens | 2,870,049 | 794,779 |
| Output tokens | 99,162 | 14,164 |
| Total tokens | 3,098,980 | 844,045 |
| Total cost | $0.866 | $0.220 |

Agentic tool counts from the trace:

| Tool | Calls |
| --- | ---: |
| `code_diver_h3_search` | 163 |
| `code_diver_rerank` | 85 |
| `code_diver_read` | 75 |
| `code_diver_outline` | 39 |
| `code_diver_rg` | 32 |
| `code_diver_symbols` | 26 |
| `code_diver_grep` | 25 |

The H3 search tool itself is fast in `fast` mode: mean about 325 ms, p95 about 692 ms. The expensive part is the open-ended agent loop: model calls, unscoped grep/rg, and repeated verification rounds.

## Interpretation

The current Agentic H3 implementation does **not** beat Pure H3.

Pure H3 is better on every quality metric that matters here:

- +0.20 Hit@1;
- +0.22 Hit@3;
- +0.19 Hit@5;
- +0.20 Hit@10;
- +0.193 nDCG@10;
- +0.185 MAP@10.

It is also cheaper and faster on this run.

The result should be read precisely:

```text
Agentic fast-H3 currently loses to Pure full-H3.
```

This does not prove that all agentic search is bad. It proves that the current agent layer, when paired with the fast H3 candidate tool, is not yet adding enough value to pay for its extra calls.

## Why Agentic Lost

1. **Different candidate generator.** Pure H3 uses the full manifest-union branch with structured probes. Agentic H3 uses the faster H3 tool by default. That makes the comparison realistic for latency, but not an isolated test of agent reasoning.
2. **Unscoped text probes are expensive.** The agent sometimes calls grep/rg broadly over IntelliJ. Those calls add seconds and often return weak evidence.
3. **The model over-searches.** Even after enough candidates exist, it may continue tool calls instead of reranking. We added forced rerank after two candidate-producing passes, but the loop is still heavier than the deterministic runner.
4. **LLM planning is not automatically better than tuned retrieval.** The tuned deterministic branch already encodes strong retrieval behavior: profile union, outline/symbol/rg probes, and one focused rerank.

## Fixes From Trace Analysis

We found three runtime issues that made the first agentic runs worse than the idea itself:

| Issue | Evidence | Fix |
| --- | --- | --- |
| Unscoped grep/rg after candidates | `code_diver_rg` could scan the full IntelliJ tree for a vague pattern even after H3 returned candidate files. | Executor scopes unscoped grep/rg to the candidate bank after candidates exist. |
| Parallel race between H3 and probes | If the model requested H3 and rg in one parallel batch, rg ran before the candidate bank was populated. | Orchestrator stages first-pass candidate calls before delayed unscoped probes, while preserving result order. |
| Broad symbol paths | A call such as `code_diver_symbols(path="java")` scanned 47,194 files and took 17.5s in trace. | Symbols require path/candidate bank under H3/search. Broad symbol directories are intersected with candidate files once candidates exist. |

The fixes are intentionally runtime-enforced. The prompt and manifest now describe the policy, but correctness does not depend on the model obeying every instruction.

Early bounded traces show the expected latency effect: grep/rg probes dropped from multi-second broad scans to low hundreds of milliseconds. The first bounded Gemini Lite run still did not beat Pure H3, so the next valid run must include all three bounded policies: scoped grep/rg, staged batches, and scoped symbols.

The full bounded Gemini Lite run confirms the split:

| Tool | Calls | Mean ms | P95 ms | Max ms |
| --- | ---: | ---: | ---: | ---: |
| `code_diver_h3_search` | 150 | 552.0 | 670.1 | 4,937.0 |
| `code_diver_symbols` | 32 | 13.6 | 21.5 | 195.9 |
| `code_diver_rg` | 60 | 191.9 | 390.4 | 849.8 |
| `code_diver_grep` | 22 | 287.4 | 368.4 | 441.0 |
| `code_diver_rerank` | 76 | 2,507.8 | 4,606.6 | 5,457.0 |

So the tool-layer bug is largely fixed. The remaining problem is agent policy and candidate quality: bounded Agentic H3 made 572 model calls and 479 tool calls for 100 cases, but still dropped to Hit@10 `0.75`. It is now clear that the current open-ended agent loop is not the right default path.

The local Qwen3.5 4B bounded run reached better quality than bounded Gemini Lite on this 100-case slice: Hit@10 `0.85` and Hit@1 `0.65`. The cost is latency: mean `44.6s` and p95 `52.7s`. Its tool calls were fast after bounding, but local generative rerank/model turns averaged several seconds each. This makes Qwen useful as a local quality hypothesis, not yet as an interactive default.

Current interpretation:

```text
Pure H3 full union is the baseline.
Bounded Agentic H3 is a diagnostic/hard-case experiment, not a production winner.
```

## Next Experiments

The next fair matrix should separate the variables:

| Hypothesis | Purpose |
| --- | --- |
| Fast H3 deterministic + Gemini Lite rerank | Is the quality drop caused by fast H3 candidates or by agent behavior? |
| Agentic H3 with scoped grep/rg only | Does restricting text tools recover latency without hurting quality? |
| Agentic planner over Pure H3 candidate generation | Can the LLM improve query variants while keeping deterministic candidate construction? |
| Pure H3 first, agent only on low-confidence cases | Use agentic reasoning only where the deterministic result is uncertain. |
| Qwen3-Reranker cross-encoder after Pure H3 | Test a cheaper specialized reranker before spending tokens on an LLM. |
| Confidence-gated agent | Run Pure H3 first; invoke the agent only when top score margin, rerank confidence, or source agreement is weak. |

Current recommendation: keep **Pure H3 + Gemini 3.1 Flash Lite rerank** as the best active baseline, and treat agentic search as a gated hard-case layer until it proves a quality gain.
