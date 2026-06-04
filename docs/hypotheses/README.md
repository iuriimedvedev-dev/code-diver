# Code Diver Hypothesis Index

This index is the reviewer entry point for Code Diver research hypotheses. It normalizes the scattered reports into stable scenario IDs and points to the detailed catalog in [catalog.md](./catalog.md). Use [template.md](./template.md) for new hypotheses.

## Current Direction

The active architecture is:

```text
local semantic file-metadata embeddings
-> Pure H3 deterministic hybrid file candidates
-> optional H5 top-10 LLM ranking
-> answer-set-aware or public-slice evaluation
```

Current accepted direction:

| Layer | Default | Why |
| --- | --- | --- |
| Persistent index | File-first metadata/manifests, not global line chunks | Compact enough to keep hot and reduces duplicate chunk pressure. |
| Candidate generator | Pure H3 hybrid file candidates | Fast, deterministic, and above the `Hit@10 >= 0.95` target on the local CodeSearchNet positive slice. |
| Quality layer | H5 with Gemini 3.1 Flash Lite when API ranking is allowed | Best measured local positive-slice quality/cost tradeoff. |
| Hard-case path | Agentic search only behind a gate | Current open-ended agent loops are slower, costlier, and weaker than Pure H3 on saved comparisons. |
| Public claim | No official SOTA claim | Current CodeSearchNet results are local positive-slice numbers, not full-corpus MTEB scores. |

Evidence: [current research state](../current-research-state-2026-06-04.md), [final report](../final-report-2026-06-03.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md).

## Decision Timeline

| Era | Scenario | Status | Decision |
| --- | --- | --- | --- |
| Early baseline | Vector line chunks with hash/local embeddings | superseded | Useful as a harness, not a quality architecture. |
| Early baseline | Recursive search | rejected as default | More latency without consistent quality gain in saved runs. |
| Early baseline | Deterministic GraphRAG expansion | active support, not standalone winner | Keep graph features as hybrid signals; standalone graph did not beat vector/hybrid controls. |
| H1 | File-locator index | accepted as design principle | Compact file-level locator is viable at IntelliJ scale. |
| H1b | File + signature-only symbols | proposed / unproven | Plausible quality-vs-footprint extension; full quality impact not measured. |
| H2A | Locator -> structured outline/symbol/rg/read -> rerank | superseded by H3, but branch winner over H2B | Beats ephemeral indexing in the saved six-way matrix. |
| H2B | Locator -> ephemeral deep index -> rerank | rejected as default | Slower and lower Hit@10 than H2A in saved IntelliJ matrix. |
| H3 | Hybrid profile union / manifest file candidates | accepted | Current deterministic candidate-generation baseline. |
| H4 | LLM query planner / multi-query variants | research only | Fixed some misses, but full evidence is partial and costlier. |
| Agentic H3 | Open-ended tool loop over H3 tools | rejected as default | Worse quality and higher cost than Pure H3 in valid 100-case IntelliJ comparison. |
| H5 | H3 candidates + final LLM ranker | accepted quality layer | Best measured quality on the public local positive slice. |
| Reranker variants | Gemini 3.5, Gemini Lite, Qwen3.5 4B, cross-encoder candidates | mixed | Gemini 3.5 is oracle/costly; Gemini Lite is active tradeoff; Qwen local is viable but slow; CE rerankers remain follow-up. |
| Embedding variants | Qwen3 0.6B, Qwen3 4B, EmbeddingGemma, Gemini, Voyage | active matrix | Qwen3 0.6B is current practical default; stronger local/API embedders need same-stack reruns. |
| Public benchmark | CodeSearchNet/MTEB Python positive slice | active internal benchmark | Strong internal comparison, not official SOTA. |

## Quick Comparison Table

| ID | Title | Status | Best Known Result | Main Reason |
| --- | --- | --- | --- | --- |
| `BASE-VECTOR` | Vector-only line/chunk retrieval | superseded | Protogen local `mxbai-embed-large` vector Hit@10 `0.90`; hash baselines much lower | Real embeddings matter; chunk-only/global vector is not enough for current goals. |
| `BASE-RECURSIVE` | Recursive retrieval | rejected as default | Protogen `mxbai-embed-large` recursive Hit@10 `0.90`, MRR below vector; slower | Expansion did not justify latency. |
| `BASE-GRAPH` | Standalone graph retrieval | active support | Protogen graph often matched vector but did not improve it | Keep graph as a bounded hybrid signal. |
| `H1` | Compact file locator | accepted | IntelliJ local Qwen locator Hit@10 `0.890`; Gemini control lexical-heavy Hit@10 `0.906` | Good candidate recall under sub-1GB persistent footprint. |
| `H1B` | File locator + signature symbols | proposed | Index-size estimate only: 523,137 vectors, 1.61 GB raw 768d vectors | Not enough quality evidence yet. |
| `H2A` | Structured post-locator probes | superseded / branch winner | Gemini 3.5 old narrow matrix Hit@10 `0.856`; Gemini Lite `0.850` | Better than H2B, but weaker than H3 answer-set direction. |
| `H2B` | Ephemeral candidate-file index | rejected as default | Gemini 3.5 old narrow matrix Hit@10 `0.635`; Gemini Lite `0.630` | Added build/query cost and reduced recall. |
| `H3` | Pure H3 hybrid file candidates | accepted | CodeSearchNet local positive slice Hit@10 `0.961`, mean `555 ms` | Fastest accepted quality baseline with no ranking API. |
| `H3-INTELLIJ-ORACLE` | H3 manifest + Gemini 3.5 | oracle | IntelliJ answer-set Hit@10 `0.976`, cost `$34.94` per 1000-case run | Shows ceiling, too expensive for routine loops. |
| `H3-AGENTIC` | Agentic H3 tool loop | rejected as default | Agentic Gemini Lite Hit@10 `0.80` vs Pure H3 + Gemini Lite `1.00` on 100 IntelliJ cases | More calls, more cost, worse quality. |
| `H4` | Multi-query planner before retrieval | research only | Partial 175-case matrix; Hit@10 `0.869` Gemini Lite, `0.863` Gemini 3.5 | Some case-level fixes, incomplete full-run evidence. |
| `H5` | H3 + top-10 LLM ranker | accepted quality layer | CodeSearchNet local positive slice Hit@10 `0.982`, Hit@1 `0.904` with Gemini Lite | Best measured quality/cost tradeoff. |
| `H5-LOCAL` | H3 + local Qwen3.5 4B ranker | fallback | CodeSearchNet local positive slice Hit@10 `0.967`, mean `7708 ms` | No API spend, but not interactive default. |

## Where To Read Next

| Need | Document |
| --- | --- |
| Structured hypothesis details | [catalog.md](./catalog.md) |
| Reusable fields | [template.md](./template.md) |
| Metric definitions | [metrics.md](../metrics.md) |
| Current research snapshot | [current-research-state-2026-06-04.md](../current-research-state-2026-06-04.md) |
| Final 2026-06-03 report | [final-report-2026-06-03.md](../final-report-2026-06-03.md) |
| IntelliJ answer-set gate | [intellij-answer-set-eval-2026-06-03.md](../intellij-answer-set-eval-2026-06-03.md) |
| CodeSearchNet quality slice | [codesearchnet-agentic-model-eval-2026-06-04.md](../codesearchnet-agentic-model-eval-2026-06-04.md) |
| Public benchmark caveat | [codesearchnet-market-comparison-2026-06-03.md](../codesearchnet-market-comparison-2026-06-03.md) |
| Evaluation validity risks | [eval-validity-review-2026-06-03.md](../eval-validity-review-2026-06-03.md) |
