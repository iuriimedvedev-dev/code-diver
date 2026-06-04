# Hypothesis Catalog

This catalog records Code Diver hypotheses in a comparable shape. It is intentionally evidence-linked rather than exhaustive: exact metrics appear only when already present in local docs or saved report references.

Status meanings:

| Status | Meaning |
| --- | --- |
| accepted | Use as the current default or baseline. |
| active | Keep in the implementation/research surface, but not a default winner. |
| proposed | Design has an estimate or rationale, but not enough measured quality. |
| superseded | Historically useful, replaced by a stronger scenario. |
| rejected | Do not use as the default without new evidence. |
| invalid | Saved run should not be used for quality selection. |

## BASE-VECTOR - Vector / Line-Chunk Retrieval

| Field | Value |
| --- | --- |
| ID | `BASE-VECTOR` |
| Status | superseded |
| Motivation | Establish a cheap baseline for semantic retrieval and prove whether embeddings are the main quality lever. |
| Assumptions | A single vector search over indexed code items can retrieve relevant files without graph expansion or reranking. |
| Index composition | Early configs used line chunks and optional symbols; later protogen controls used line+symbol+AST graph items. Exact composition varies by config. |
| Search/ranking flow | Query embedding -> vector top-k -> ranked results. |
| Model/provider matrix | Hash-token harness, local `mxbai-embed-large`, Vertex/Gemini smoke embeddings. |
| Dataset | `datasets/protogen_eval.jsonl`, `datasets/protogen_eval_100.jsonl`, CodeSearchNet hash harness; label shapes vary. |
| Metrics | Protogen local `mxbai-embed-large` vector Hit@10 `0.90`, MRR `0.663`; CodeSearchNet hash vector chunks Hit@10 `0.476`, nDCG `0.304`. |
| Cost/latency/index-size | Protogen Qdrant local vector eval was much faster than JSON search; exact persistent index sizes vary by run. |
| Result summary | Real embeddings made vector retrieval usable; hash vectors are a reproducibility harness only. Pure vector/chunk retrieval is no longer the architecture target. |
| Decision | Superseded by hybrid file-first H3. |
| Failure modes | Duplicate chunk pressure, weak file-level ranking, hash embeddings hiding semantic signal, dataset-specific label shape. |
| Follow-ups | Keep hash/vector harness only for deterministic no-key smoke checks. |
| Links | [research notes](../research.md), [metrics current runs](../metrics.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/protogen-baseline.yml`, `configs/codesearchnet-mteb-python-hash.yml` |

## BASE-RECURSIVE - Recursive Retrieval

| Field | Value |
| --- | --- |
| ID | `BASE-RECURSIVE` |
| Status | rejected as default |
| Motivation | Test whether retrieve -> inspect -> re-query improves ambiguous code-navigation queries. |
| Assumptions | Follow-up queries derived from initial hits will improve coverage enough to offset added latency. |
| Index composition | Same persistent index as the vector controls for each run. |
| Search/ranking flow | Vector seed search -> read/extract references -> repeat for configured rounds -> merge/dedupe. |
| Model/provider matrix | No required LLM in the basic recursive strategy; uses the active embedding provider. |
| Dataset | Protogen 10/100 historical runs. |
| Metrics | Protogen `mxbai-embed-large` recursive Hit@10 `0.90`, MRR `0.612`, below vector MRR `0.663`; Qdrant recursive took `1.4s` vs vector `0.4s` on the 10-case table. |
| Cost/latency/index-size | Extra search/read rounds increased latency; no separate index-size impact. |
| Result summary | Recursive search did not consistently improve quality over vector/hybrid controls. |
| Decision | Not a default path. Keep only as a research strategy if a new query-expansion implementation is tested. |
| Failure modes | Expansion anchored on weak initial hits, duplicated evidence, more latency without candidate recall gain. |
| Follow-ups | If revisited, compare against H3 candidate recall and per-bucket workflow metrics. |
| Links | [research notes](../research.md), [spec retrieval strategies](../spec/03-retrieval-strategies.md), [metrics](../metrics.md) |

## BASE-GRAPH - Deterministic GraphRAG Retrieval

| Field | Value |
| --- | --- |
| ID | `BASE-GRAPH` |
| Status | active support, not standalone winner |
| Motivation | Code questions often require relationships such as imports, containment, references, and calls that vector similarity alone may miss. |
| Assumptions | Deterministic AST/import/symbol edges can improve multi-hop recall without LLM indexing cost. |
| Index composition | Graph nodes are indexed code items; edges include same-file adjacency, imports, lexical references, containment, and Python AST calls in current docs. |
| Search/ranking flow | Vector seed search -> graph neighbor expansion -> score propagation/fusion. In H3, graph is a bounded hybrid signal rather than the whole strategy. |
| Model/provider matrix | Uses the active embedding provider; graph construction is deterministic. |
| Dataset | Protogen historical runs; IntelliJ H3 uses graph artifacts/aliases in some configs, with graph retrieval disabled in the final answer-set command. |
| Metrics | Protogen `mxbai-embed-large` graph Hit@10 `0.90`, MRR `0.663`, matching vector in that run; deterministic hybrid graph-boost Hit@10 `0.90`, precision `0.469`. |
| Cost/latency/index-size | Early AST graph was 177 MB before bounded imports; current file-locator graph JSON around 248 MB for IntelliJ; graph-specific latency varies. |
| Result summary | Graph features are useful infrastructure, but standalone graph retrieval did not become the winner. |
| Decision | Keep as bounded/query-aware hybrid support; do not use standalone graph as the quality default. |
| Failure modes | High fanout, stale graph artifacts, graph neighbors that add related but irrelevant candidates. |
| Follow-ups | Add stricter query-aware traversal and better workflow-bucket evidence before increasing graph depth. |
| Links | [architecture](../architecture.md), [metrics graph trace metrics](../metrics.md), [optimization audit](../optimization-audit.md), [spec graph](../spec/05-graph.md) |

## H1 - Compact File-Locator Index

| Field | Value |
| --- | --- |
| ID | `H1` |
| Status | accepted design principle |
| Motivation | Large repos should not keep every method body/chunk hot in the persistent vector DB. The first stage should answer "which files should we inspect?" |
| Assumptions | File metadata, imports, symbols, path, and file heads are enough to get the right file into a small candidate pool. |
| Index composition | One `file_summary` vector per file; no line chunks, structural chunks, or symbol body chunks. IntelliJ measured 74,906 vectors, 172.95 MB payload text. |
| Search/ranking flow | Query -> hybrid file locator -> top 20-50 files -> structured probes or reranker. |
| Model/provider matrix | Gemini API embedding control at 768d; local Qwen3-Embedding-0.6B at 1024d. |
| Dataset | IntelliJ 1,000-case file-location sweep. Mostly single-file expected answers. |
| Metrics | Gemini lexical-heavy Hit@1 `0.744`, Hit@10 `0.906`; local Qwen baseline Hit@1 `0.628`, Hit@10 `0.890`. |
| Cost/latency/index-size | Gemini control observed Qdrant storage 378 MB plus graph JSON 247.86 MB; local Qwen observed Qdrant 450 MB plus graph JSON 247.86 MB; local Qwen index build about 26.2 min. |
| Result summary | Compact file-level indexing is viable at IntelliJ scale and keeps the persistent footprint under 1 GB before runtime overhead. |
| Decision | Accepted. This becomes the persistent locator foundation for H3/H5. |
| Failure modes | Correct file can be present but ranked too low; vague semantic queries may need better query variants or reranking. |
| Follow-ups | Improve rank ordering with H3 profile union and H5 ranking; test stronger local embedders. |
| Links | [Explanation H1](../Explanation.md), [IntelliJ file-locator sweep](../intellij-file-locator-sweep-2026-06-02.md), `configs/intellij-community-file-locator.yml` |

## H1B - File Locator Plus Signature-Only Symbols

| Field | Value |
| --- | --- |
| ID | `H1B` |
| Status | proposed / unproven |
| Motivation | Improve API/symbol/workflow recall without permanently indexing method bodies. |
| Assumptions | Signature-only symbol vectors add navigation signal while avoiding code-body duplication. |
| Index composition | `file_summary` plus signature-only `symbol` items. IntelliJ scan-only estimate: 523,137 vectors, 215.66 MB payload, 1.61 GB raw 768d vectors. |
| Search/ranking flow | Query -> hybrid file/symbol locator -> candidate file aggregation -> probes/rerank. |
| Model/provider matrix | Not fully measured; estimates in docs assume 768d vectors. |
| Dataset | IntelliJ scan estimate; quality run not documented. |
| Metrics | not measured |
| Cost/latency/index-size | Footprint plausibly inside 1-3 GB, but build cost and vector RAM are much higher than H1. |
| Result summary | Plausible quality-vs-footprint extension, but not accepted without quality evidence. |
| Decision | Proposed. Do not make default until measured against H1/H3 on answer-set and public slices. |
| Failure modes | More vectors can add duplicate/noisy candidates and slow search. |
| Follow-ups | Run H1 vs H1B with identical H3/H5 ranking and report file Hit@1/3/5/10, nDCG, latency, storage. |
| Links | [Explanation H1b](../Explanation.md), [architecture deterministic hybrid indexing](../architecture.md) |

## H2A - Structured Post-Locator Probes

| Field | Value |
| --- | --- |
| ID | `H2A` |
| Status | superseded by H3, but accepted over H2B in the post-locator branch test |
| Motivation | After the locator finds likely files, inspect them with deterministic file tools instead of permanently indexing all bodies. |
| Assumptions | `outline`, `symbols`, `rg`, `grep`, and bounded reads can find exact evidence more cheaply than temporary vectorization. |
| Index composition | Fixed compact local Qwen file-locator index for IntelliJ; no branch-specific persistent index changes. |
| Search/ranking flow | Locator top N -> outline/symbol/rg/grep/read probes over candidate files -> listwise rerank. |
| Model/provider matrix | Gemini 3.1 Flash Lite, Gemini 3.5 Flash, local Qwen3.5 4B OptiQ 4bit. |
| Dataset | Original narrow IntelliJ 1,000-case expected set. Absolute metrics are not final answer-set quality metrics. |
| Metrics | Gemini Lite Hit@10 `0.850`, mean `2319 ms`, cost `$2.16`; Gemini 3.5 Hit@10 `0.856`, mean `3070 ms`, cost `$13.51`; Qwen local Hit@10 `0.825`, mean `11517 ms`. |
| Cost/latency/index-size | No temporary vectors; branch made 1,000 locator and rerank calls plus structured probes in full Gemini rows. |
| Result summary | H2A beat H2B on quality and speed in the saved six-way matrix. |
| Decision | Keep the lesson: structured probes are better than ephemeral indexing in this implementation. Superseded as a named architecture by H3/H5. |
| Failure modes | Old evaluator undercounted broad multi-file answers; the answer-set six-way rerun was still pending in the source doc. |
| Follow-ups | Replace old narrow metrics with full answer-set rerun if completed. |
| Links | [IntelliJ H2 matrix](../intellij-h2-matrix-overnight-2026-06-02.md), [IntelliJ answer-set eval](../intellij-answer-set-eval-2026-06-03.md), `configs/intellij-postrank-h2.yml` |

## H2B - Ephemeral Candidate-File Deep Index

| Field | Value |
| --- | --- |
| ID | `H2B` |
| Status | rejected as default |
| Motivation | Test whether building temporary syntax-aware vectors over top locator files beats direct structured inspection. |
| Assumptions | A local hot embedding model can cheaply build a better semantic view of the candidate-file neighborhood. |
| Index composition | Same persistent locator as H2A; per-query temporary syntax-aware chunks over candidate files. |
| Search/ranking flow | Locator top N -> build temporary candidate-file chunks/vectors -> local vector search -> listwise rerank. |
| Model/provider matrix | Gemini 3.1 Flash Lite, Gemini 3.5 Flash, local Qwen3.5 4B OptiQ 4bit. |
| Dataset | Original narrow IntelliJ 1,000-case expected set; Qwen row is 50-case partial for H2B. |
| Metrics | Gemini Lite Hit@10 `0.630`, mean `7301 ms`; Gemini 3.5 Hit@10 `0.635`, mean `8436 ms`; Qwen partial Hit@10 `0.640`, mean `11462 ms`. |
| Cost/latency/index-size | Gemini Lite branch built 187,659 temporary vectors across 1,000 cases; Gemini 3.5 built 187,743. |
| Result summary | H2B was slower and substantially lower quality than H2A in the saved matrix. |
| Decision | Rejected as default. Revisit only with a different chunking/aggregation design or if CodeSearchNet function-level results contradict IntelliJ. |
| Failure modes | Temporary chunks displaced good locator files; build/query cost dominated; old answer labels were narrow. |
| Follow-ups | If revisited, use fixed top-N file inputs, source-balanced candidate mixing, and separate `ephemeral_build_ms` / `ephemeral_query_ms`. |
| Links | [Explanation H2](../Explanation.md), [IntelliJ H2 matrix](../intellij-h2-matrix-overnight-2026-06-02.md), [IntelliJ postrank H2](../intellij-postrank-h2-2026-06-02.md) |

## H3 - Pure Hybrid File Candidate Generator

| Field | Value |
| --- | --- |
| ID | `H3` |
| Status | accepted |
| Motivation | Improve H1 candidate generation with hybrid signal fusion, profile union, file manifests/summaries, and deterministic ranking before any LLM spend. |
| Assumptions | High candidate recall and good enough ordering can be achieved deterministically when file-level metadata is strong. |
| Index composition | File-first metadata/manifests/summaries with local Qwen3-Embedding-0.6B in the current public quality profile; IntelliJ manifest configs use file/manifest union candidates. |
| Search/ranking flow | Query -> routed hybrid retrieval over file metadata -> profile/manifest union where configured -> ranked files. |
| Model/provider matrix | Local Qwen3-Embedding-0.6B is current practical embedding default; API embeddings and stronger local embeddings are comparison candidates. |
| Dataset | CodeSearchNet/MTEB Python local positive slice, 1,000 cases; IntelliJ answer-set eval for oracle reranked H3. |
| Metrics | CodeSearchNet Pure H3 quality Hit@1 `0.823`, Hit@10 `0.961`, nDCG `0.900`, mean `555 ms`; IntelliJ H3 + Gemini 3.5 oracle Hit@10 `0.976` after rerank. |
| Cost/latency/index-size | Pure H3 has no ranking API call; CodeSearchNet mean query latency `555 ms`. Exact public quality index size not documented in the source reports. |
| Result summary | H3 is the fastest accepted quality baseline and exceeds the project Hit@10 target on the local positive slice. |
| Decision | Accepted as the production baseline candidate generator and no-API fallback. H5 is the default quality path when an LLM ranker is available. |
| Failure modes | Public positive slice is not official full-corpus MTEB; file-level metadata may dilute function-level CodeSearchNet targets; candidate recall still caps reranking. |
| Follow-ups | Add large-negative/full-corpus public profile; compare Qwen3 4B, EmbeddingGemma, Gemini, and Voyage Code with the same H3 stack. |
| Links | [current research state](../current-research-state-2026-06-04.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/codesearchnet-mteb-python-h5-qwen-quality.yml`, `configs/codesearchnet-mteb-python-pure-h3.yml` |

## H3-INTELLIJ-ORACLE - H3 Manifest Union Plus Gemini 3.5

| Field | Value |
| --- | --- |
| ID | `H3-INTELLIJ-ORACLE` |
| Status | oracle / not routine default |
| Motivation | Prove the Hit@10 target is reachable on the large internal IntelliJ answer-set evaluation. |
| Assumptions | H3 manifest candidates have enough recall and Gemini 3.5 Flash can rank broad answer-set candidates well. |
| Index composition | `configs/intellij-postrank-h3-manifest.yml`; manifest + summary hybrid union over IntelliJ. |
| Search/ranking flow | H3 manifest union top candidates -> Gemini 3.5 Flash file-first listwise rerank -> final ranked files. |
| Model/provider matrix | Vertex `gemini-3.5-flash` reranker. |
| Dataset | `datasets/intellij_eval_1000.answer_sets.jsonl`, 1,000 cases, answer sets with exact paths and `glob:` labels. |
| Metrics | Hit@1 `0.871`, Hit@3 `0.903`, Hit@5 `0.943`, Hit@10 `0.976`, Recall@10 `0.964`, Precision@10 `0.419`, MRR `0.898`, nDCG `0.908`. |
| Cost/latency/index-size | Mean `6542 ms`, p95 `9285 ms`, estimated cost `$34.94`, 22.6M tokens for 1,000 cases. |
| Result summary | The setup passed the Hit@10 target and the lower 95% CI bound was above 0.95, but the evaluation has known optimism/label-governance caveats. |
| Decision | Use as quality ceiling/oracle, not routine experiment loop. |
| Failure modes | `answer_sets` is permissive; no-glob estimate was about `0.946`; some globs matched no files in later validation; cost is high. |
| Follow-ups | Report full/no-glob/exact-only scores; add fail-fast/degraded gates; run cheaper Gemini Lite clean H3 answer-set sweep. |
| Links | [IntelliJ answer-set eval](../intellij-answer-set-eval-2026-06-03.md), [final quality conclusions](../final-search-quality-conclusions-2026-06-03.md), [eval validity review](../eval-validity-review-2026-06-03.md), `configs/intellij-postrank-h3-manifest.yml` |

## H3-AGENTIC - Open-Ended Agentic H3

| Field | Value |
| --- | --- |
| ID | `H3-AGENTIC` |
| Status | rejected as default |
| Motivation | Test whether an LLM controlling H3 search, probes, reads, and rerank can outperform deterministic H3. |
| Assumptions | The model can generate better query variants/tool plans than static H3 without losing recall or wasting calls. |
| Index composition | Same H3/manifest index as the deterministic baseline for each comparison where possible. |
| Search/ranking flow | LLM loop -> H3 search and inspection tools -> optional reads/probes -> rerank/final result, with bounded/fixed variants in later runs. |
| Model/provider matrix | Gemini 3.1 Flash Lite, local Qwen3.5 4B, Gemma variants in public/hash smoke docs. |
| Dataset | IntelliJ 100-case comparison; CodeSearchNet hash harness and Qwen quality notes. |
| Metrics | IntelliJ: Pure H3 + Gemini Lite Hit@10 `1.00`, cost `$0.220`; Agentic H3 + Gemini Lite Hit@10 `0.80`, cost `$0.866`; bounded Agentic Gemini Lite Hit@10 `0.75`; bounded local Qwen Hit@10 `0.85`, mean `44,570 ms`. |
| Cost/latency/index-size | Agentic Gemini Lite made 576 model calls and 445 tool calls vs 100/100 for Pure H3 in the 100-case comparison. |
| Result summary | Current agentic H3 spends more calls and returns worse rankings than deterministic H3. |
| Decision | Not default. Keep only as hard-case/gated research. |
| Failure modes | Over-searching, unscoped probes, candidate generator mismatch, tool protocol errors, replacing deterministic tail after LLM choices. |
| Follow-ups | Test confidence-gated agent after Pure H3, planner-only variants, and deterministic candidate construction with agent only for low-confidence cases. |
| Links | [agentic H3 comparison](../agentic-h3-comparison-2026-06-03.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), `configs/intellij-postrank-h3-manifest.yml`, `configs/codesearchnet-mteb-python-h3-agentic.yml` |

## H4 - LLM Query Planner / Multi-Query Profile Union

| Field | Value |
| --- | --- |
| ID | `H4` |
| Status | research only |
| Motivation | Fix failures where a single semantic query misses the right file, but a symbol-like or alternate query retrieves it. |
| Assumptions | LLM-generated variants and deterministic symbol hypotheses can raise candidate recall before reranking. |
| Index composition | Same file-locator/H3-style persistent index as H2/H3 runs. |
| Search/ranking flow | LLM query planner -> multiple query variants -> profile union -> structured probes -> rerank. |
| Model/provider matrix | Gemini 3.1 Flash Lite and Gemini 3.5 Flash partial 175-case rows; Qwen rows missing in the summarized matrix. |
| Dataset | Original narrow IntelliJ expected set, 175-case partial rows in the saved matrix. |
| Metrics | Gemini Lite partial Hit@10 `0.869`, mean `12745 ms`; Gemini 3.5 partial Hit@10 `0.863`, mean `12744 ms`. |
| Cost/latency/index-size | Adds planner calls, query variants, and more union profile calls; partial rows have wide CI. |
| Result summary | H4 fixed at least one concrete miss (`ProjectManagerImpl.kt`) but did not produce enough full-run evidence to become the default. |
| Decision | Research-only. Keep the insight that pre-retrieval query variants can help, but require stronger cost/quality proof. |
| Failure modes | Planner cost, variant noise, partial-run instability, old evaluator labels. |
| Follow-ups | Compare planner-only over Pure H3 candidates and confidence-gated planning on answer-set/public quality datasets. |
| Links | [IntelliJ H2 postrank H3/H4 update](../intellij-postrank-h2-2026-06-02.md), [IntelliJ H2 matrix](../intellij-h2-matrix-overnight-2026-06-02.md), `configs/intellij-postrank-h2.yml` |

## H5 - H3 Candidates Plus Top-10 LLM Ranking

| Field | Value |
| --- | --- |
| ID | `H5` |
| Status | accepted quality layer |
| Motivation | Improve top-ordering after H3 has already achieved high candidate recall. |
| Assumptions | A bounded listwise LLM ranker can improve Hit@1/MRR/nDCG without replacing candidate generation with an open-ended agent. |
| Index composition | Same H3 local Qwen3-Embedding-0.6B file-metadata index in current CodeSearchNet quality runs. |
| Search/ranking flow | H3 hybrid candidates -> top-10 LLM rerank -> ranked file results. |
| Model/provider matrix | Gemini 3.1 Flash Lite active quality tradeoff; local Qwen3.5 4B compact fallback; Gemini 3.5 Flash oracle in IntelliJ. |
| Dataset | CodeSearchNet/MTEB Python local positive slice, 1,000 cases. |
| Metrics | Gemini Lite H5 Hit@1 `0.904`, Hit@10 `0.982`, nDCG `0.948`, MAP `0.936`, mean `3020 ms`; local Qwen H5 Hit@10 `0.967`, mean `7708 ms`. |
| Cost/latency/index-size | Gemini Lite adds about `+2.47s/query` over Pure H3 on the public slice; token cost exists but exact 1,000-case H5 public cost is not stated in the source doc. |
| Result summary | H5 with Gemini Lite is the best measured quality/cost tradeoff on the current public local positive slice. |
| Decision | Accepted as the default quality path. Pure H3 remains the fastest/no-API fallback and the candidate generator under H5. |
| Failure modes | Candidate recall ceiling, prompt size for local rankers, API cost/quotas, public-slice not official full-corpus MTEB. |
| Follow-ups | Run stronger embedding models with the same H5 protocol; add a true cross-encoder reranker baseline. |
| Links | [current research state](../current-research-state-2026-06-04.md), [final report](../final-report-2026-06-03.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), `configs/codesearchnet-mteb-python-h5-qwen-quality.yml` |

## H6.1 - Calibrated Hybrid Candidate Weights

| Field | Value |
| --- | --- |
| ID | `H6.1` |
| Status | active calibration candidate |
| Motivation | Replace manual H3/H5 hybrid weights with weights chosen on a train split and validated on held-out cases. |
| Assumptions | The existing hybrid signals are useful, but their relative weights should be calibrated against file-level metrics rather than hand-picked. |
| Index composition | Same H5 file-metadata index as `configs/codesearchnet-mteb-python-h5-qwen-quality.yml`: local Qwen3-Embedding-0.6B, `file_summary` + `file_manifest`, no code-body chunks. |
| Search/ranking flow | H3 candidate generation -> collect score components -> grid/linear weight sweep on train -> validate frozen weights -> optionally run H5 LLM rerank over calibrated candidates. |
| Model/provider matrix | Current calibration uses Qwen3-Embedding-0.6B candidates only; no LLM calls during calibration. |
| Dataset | CodeSearchNet/MTEB Python local positive slice, 1,000 cases, split 700 train / 300 validation, seed `17`. |
| Metrics | Manual H5 validation file Hit@1 `0.837`, Hit@5 `0.947`, Hit@10 `0.960`, MRR@10 `0.888`; best calibrated candidate file Hit@1 `0.843`, Hit@5 `0.953`, Hit@10 `0.960`, MRR@10 `0.893`. |
| Cost/latency/index-size | Calibration tested 1,296 profiles in `862.6s`, including `576.5s` context collection; no API or LLM cost. |
| Result summary | Calibration gives a small head-ranking gain but no coverage gain. It is a candidate for a locked final eval, not yet a replacement for product defaults. |
| Decision | Keep manual H5 as product default until calibrated weights win a locked final run and then H5 LLM rerank is re-evaluated over calibrated candidates. |
| Failure modes | Flat validation plateau, possible split overfit, route-specific weight rewrites not separately learned, graph signal may be weak because default H5 graph has limited edge types. |
| Follow-ups | Run larger 10k calibration if dataset is available; test finer/medium grid; learn route-specific profiles for `semantic`, `path_symbol`, and `workflow`. |
| Links | [H5 hybrid weight calibration](../h5-hybrid-weight-calibration-2026-06-04.md), `.code-diver/reports/h5-hybrid-weight-calibration-codesearchnet-1000.json`, `scripts/calibrate_hybrid_weights.py` |

## H6.2 - Learned MLP Candidate Scorer

| Field | Value |
| --- | --- |
| ID | `H6.2` |
| Status | active research, rejected as current default |
| Motivation | Test whether a tiny learned scorer over hybrid features can learn non-linear interactions or per-candidate dynamic weights that fixed weighted sums miss. |
| Assumptions | Features such as vector score, lexical score, path score, symbol coverage, graph score, file vote, and item-kind weight may interact non-linearly; a 1-3 layer MLP or dynamic weight-vector predictor might improve head ranking. |
| Index composition | Same H5 file-metadata index and same candidate feature cache as H6.1. |
| Search/ranking flow | H3 candidate generation -> feature cache -> candidate-level binary labels from expected files -> NumPy MLP scorer. `scalar` mode predicts one candidate score; `weights` mode predicts a vector over hybrid signals and scores by weighted sum. |
| Model/provider matrix | No embedding/model changes; local NumPy MLP only. This is not a generative LLM and adds no API cost. |
| Dataset | Smoke uses the 80/20 split and cached H6 features; intended full run is 700/300 and then 10k if available. |
| Metrics | Smoke manual/grid validation file Hit@1 `0.600`, Hit@5 `0.850`, Hit@10 `0.850`, MRR `0.708`; scalar MLP Hit@1/3/5/10 `0.550`, MRR `0.550`; dynamic-weight MLP Hit@1 `0.600`, Hit@3 `0.750`, Hit@5 `0.800`, Hit@10 `0.850`, MRR `0.684`. |
| Cost/latency/index-size | Training is local CPU over cached candidate features. Feature collection cost is shared with H6.1; subsequent MLP runs can use `--reuse-feature-cache`. |
| Result summary | Implemented and smoke-tested. Both naive variants fail to beat the fixed/grid weights today. Dynamic weights are closer than scalar scoring, but still worse in top-ordering. |
| Decision | Keep out of defaults. Continue only with better loss design, route-specific training, or larger validation if H6.1 plateaus. |
| Failure modes | Candidate-level labels are imbalanced; MLP can overfit train candidates; binary candidate labels may not optimize listwise ranking; no feature cache means collection dominates runtime. |
| Follow-ups | Compare depth 0, 1, 2, 3; add route-specific training; add pairwise/listwise loss; test whether dynamic weights are useful only on low-confidence H3 cases. |
| Links | [H5 hybrid weight calibration](../h5-hybrid-weight-calibration-2026-06-04.md), `scripts/calibrate_hybrid_weights.py` |

## LOCAL-MODEL-AXIS - Three-Axis Local Model Search

| Field | Value |
| --- | --- |
| ID | `LOCAL-MODEL-AXIS` |
| Status | active |
| Motivation | Separate three different model choices that affect different parts of H5: embedding recall, reranking order, and agentic tool planning. |
| Assumptions | Changing several models at once hides causality. Each run should change exactly one axis against a fixed H5 baseline. |
| Index composition | Baseline index shape is H5 file-first metadata: file summaries + file manifests + bounded graph metadata, no code-body vectors by default. |
| Search/ranking flow | Baseline: H3/H5 candidate generation -> bounded reranker. Agentic variants wrap the same H3/H5 tool as a callable search primitive, then optionally inspect/rerank. |
| Model/provider matrix | Axis 1 embeddings: Qwen3-Embedding-0.6B, Qwen3-Embedding-4B, EmbeddingGemma-300M, API controls if needed. Axis 2 rerankers: Qwen3-Reranker 0.6B/4B cross-encoder, Qwen3.5 4B listwise, Gemma E2B/E4B listwise, Gemini Lite API control. Axis 3 agents: Qwen3.5 4B, Gemma E2B/E4B, Gemini Lite API control. |
| Dataset | Start with CodeSearchNet/MTEB Python 1,000-case slice, then promote winners to larger-negative/public-compatible and IntelliJ answer-set runs. |
| Metrics | Required: Hit@1/3/5/10, Recall@3/5/10, Precision@R/top-k, MRR@10, nDCG@10, latency p50/p95/mean, tokens, tool calls, index size, cache warmup time, and failure/degraded count. |
| Cost/latency/index-size | Embedding-axis runs rebuild indexes; reranker-axis runs reuse the same index; agent-axis runs reuse the same index and candidate tool but add model/tool-call cost. |
| Result summary | This is the experimental plan for local models. Existing evidence: Qwen3-Embedding-0.6B is the practical baseline; EmbeddingGemma works through Sentence Transformers but not current vLLM-Metal serving; local generative rankers have trailed Gemini Lite so far; true cross-encoder rerankers remain the highest-priority local reranker test. |
| Decision | Active. Every new local-model claim must name which axis changed and which two axes were fixed. |
| Failure modes | Mixed-axis runs cannot identify causality; local serving failures can masquerade as model quality; agentic loops can over-search and spend latency without improving recall. |
| Follow-ups | Add run manifests with axis labels; add report grouping by changed axis; run Qwen3 4B embedding once local serving is stable; test Qwen3-Reranker through a real rerank endpoint. |
| Links | [local model axis experiments](../local-model-axis-experiments-2026-06-04.md), [H5 hybrid weight calibration](../h5-hybrid-weight-calibration-2026-06-04.md), [code embedding model research](../code-embedding-model-research-2026-06-04.md), `scripts/benchmark_embedding_models.py`, `scripts/benchmark_generation_models.py` |

## EMBED-MATRIX - Local And API Embedding Candidates

| Field | Value |
| --- | --- |
| ID | `EMBED-MATRIX` |
| Status | active |
| Motivation | Candidate generation quality depends heavily on the embedding model; hash embeddings are no longer a quality signal. |
| Assumptions | Stronger code-aware or modern semantic embedders can improve H3/H5 without changing the search pipeline. |
| Index composition | Same H3/H5 file-metadata index shape should be reused for fair comparisons. |
| Search/ranking flow | Swap embedding provider/model; keep H3/H5 flow fixed. |
| Model/provider matrix | Current practical default Qwen3-Embedding-0.6B; candidates include Qwen3-Embedding-4B, EmbeddingGemma-300m, Gemini Embedding, Voyage Code 3, Jina code embeddings, Codestral Embed. |
| Dataset | Next matrix should use CodeSearchNet local positive slice and larger-negative/full-corpus public profile when available. |
| Metrics | Qwen3-Embedding-0.6B current Pure H3 CodeSearchNet Hit@10 `0.961`; 100-case same-stack smoke: Qwen0.6B file Hit@1/10 `0.750`/`0.950`, EmbeddingGemma-300M file Hit@1/10 `0.810`/`0.950`; public MTEB extract lists Qwen3-Embedding-0.6B official score `0.94325`, Qwen3-Embedding-4B `0.96004`, EmbeddingGemma-300m `0.96180`, Gemini embedding `0.96495`, Voyage Code 3 `0.96688`. |
| Cost/latency/index-size | Qwen 0.6B is already integrated and fast enough; larger/API models have unmeasured Code Diver cost in the same stack. |
| Result summary | Qwen 0.6B is the practical default today, but public benchmark data justifies testing 4B, EmbeddingGemma, Gemini, and Voyage. |
| Decision | Active model matrix. Do not claim a new winner until same-stack runs exist. |
| Failure modes | Official MTEB scores are not directly comparable to Code Diver local positive-slice metrics; API models add cost/quota; gated licenses may block local setup. |
| Follow-ups | Add run manifests with model/provider versions, config hashes, index hashes, and dataset hashes. |
| Links | [local model axis experiments](../local-model-axis-experiments-2026-06-04.md), [code embedding model research](../code-embedding-model-research-2026-06-04.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/codesearchnet-mteb-python-h5-qwen-quality.yml` |

## RERANK-MATRIX - LLM And Cross-Encoder Ranking

| Field | Value |
| --- | --- |
| ID | `RERANK-MATRIX` |
| Status | active |
| Motivation | H3 often gets the right file into the candidate set; ranking decides user-visible quality. |
| Assumptions | Bounded reranking can improve Hit@1/MRR/nDCG without increasing persistent index size. |
| Index composition | Reuse a fixed H3 candidate index for fair reranker comparisons. |
| Search/ranking flow | H3 candidates -> reranker/cross-encoder/LLM -> final ordered files. |
| Model/provider matrix | Gemini 3.5 Flash oracle; Gemini 3.1 Flash Lite active; Qwen3.5 4B local fallback; Qwen3-Reranker 0.6B/4B proposed; Gemma variants historical/local experiments. |
| Dataset | Protogen top-5 matrix, IntelliJ answer-set, CodeSearchNet local positive slice. |
| Metrics | Protogen top-5: H1c Gemini embedding + Flash-Lite file-first Hit@10 `0.94`; H5 Qwen4B embed + Qwen4B rerank Hit@10 `0.87`, mean `7020 ms`. CodeSearchNet H5 Gemini Lite Hit@10 `0.982`; H5 local Qwen Hit@10 `0.967`; 100-case Gemma 4 E4B OptiQ listwise rerank file Hit@10 `0.590`, mean `8049 ms`, worse than Pure H3 `0.950` / `558 ms` on the same split. |
| Cost/latency/index-size | Gemini 3.5 IntelliJ oracle cost `$34.94` per 1,000-case run; local Qwen avoids API spend but was slower in current loops. |
| Result summary | API LLM ranking is currently the quality winner; local generative rankers are not reliable defaults. Gemma E4B OptiQ specifically degraded H5 candidate ordering in the 100-case smoke. Cross-encoder rerankers remain the next important baseline. |
| Decision | Use Gemini Lite for quality/cost tradeoff; reserve Gemini 3.5 for oracle runs; keep local/cross-encoder work active. |
| Failure modes | Reranker can only reorder candidates it sees; prompt size dominates local latency; fail-soft rerank errors can contaminate metrics if not gated. |
| Follow-ups | Test Qwen3-Reranker via a real rerank endpoint over fixed H3 candidates; add validity status to all rerank reports. |
| Links | [local model axis experiments](../local-model-axis-experiments-2026-06-04.md), [top-5 hypotheses eval](../top5-hypotheses-eval-2026-06-02.md), [final quality conclusions](../final-search-quality-conclusions-2026-06-03.md), [eval validity review](../eval-validity-review-2026-06-03.md), `configs/intellij-postrank-h3-manifest.yml` |

## PUBLIC-BENCH - CodeSearchNet / MTEB Public Slice

| Field | Value |
| --- | --- |
| ID | `PUBLIC-BENCH` |
| Status | active internal benchmark, not official SOTA |
| Motivation | Provide a reviewer-runnable public benchmark path instead of relying on a sibling/private repo or IntelliJ-only internal data. |
| Assumptions | A local positive slice is useful for comparing Code Diver architectures quickly, even though it is not the official full-corpus protocol. |
| Index composition | Materialized positive qrel files from `mteb/CodeSearchNetRetrieval` Python; current quality profile uses Qwen3-Embedding-0.6B file metadata. |
| Search/ranking flow | Pure H3 or H5 over the generated local slice. |
| Model/provider matrix | Pure H3 no ranker; H5 Gemini Lite; H5 local Qwen3.5 4B. |
| Dataset | `.code-diver/benchmarks/mteb-codesearchnet-python/codesearchnet_python_1000.jsonl`, generated from `mteb/CodeSearchNetRetrieval` Python. |
| Metrics | Pure H3 Hit@10 `0.961`; H5 Gemini Lite Hit@10 `0.982`; H5 local Qwen Hit@10 `0.967`. |
| Cost/latency/index-size | Pure H3 mean `555 ms`; H5 Gemini Lite mean `3020 ms`; H5 local Qwen mean `7708 ms`. |
| Result summary | Strong internal architecture signal, but not comparable to public MTEB leaderboard scores. |
| Decision | Keep as current public comparison harness; do not use as official SOTA claim. |
| Failure modes | No large negative pool, not official scorer, synthetic file materialization, single-positive label shape. |
| Follow-ups | Add 20k/50k large-negative profiles and/or official-compatible scorer export. |
| Links | [current research state](../current-research-state-2026-06-04.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/codesearchnet-mteb-python-h5-qwen-quality.yml` |
