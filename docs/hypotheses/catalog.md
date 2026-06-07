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
| Links | [research notes](../research.md), [metrics current runs](../metrics.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/protogen-legacy/protogen-baseline.yml`, `configs/benchmarks/codesearchnet-mteb-python-hash.yml` |

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
| Links | [Explanation H1](../Explanation.md), [IntelliJ file-locator sweep](../intellij-file-locator-sweep-2026-06-02.md), `configs/intellij/intellij-community-file-locator.yml` |

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
| Metrics | Deterministic best 100-case variant: Hit@1 `0.800`, Hit@10 `0.970`, MRR `0.866`, nDCG `0.892`, mean `1672 ms`, worse than H6.1 deterministic Hit@1 `0.820`, MRR `0.876`. Agentic 26B-A4B 100-case: Hit@1 `0.760`, Hit@10 `0.900`, MRR `0.805`, nDCG `0.828`, beating H6.1 agentic Hit@1 `0.710`, MRR `0.768`. |
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
| Links | [IntelliJ H2 matrix](../intellij-h2-matrix-overnight-2026-06-02.md), [IntelliJ answer-set eval](../intellij-answer-set-eval-2026-06-03.md), `configs/intellij/intellij-postrank-h2.yml` |

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
| Index composition | File-first metadata/manifests/summaries. Historical H3 rows used local Qwen3-Embedding-0.6B; the current public default uses EmbeddingGemma-300M via H6.1. IntelliJ manifest configs use file/manifest union candidates. |
| Search/ranking flow | Query -> routed hybrid retrieval over file metadata -> profile/manifest union where configured -> ranked files. |
| Model/provider matrix | Local EmbeddingGemma-300M is current practical default; Qwen3-Embedding-0.6B remains the control. API embeddings and stronger local embeddings are comparison candidates. |
| Dataset | CodeSearchNet/MTEB Python local positive slice, 1,000 cases; IntelliJ answer-set eval for oracle reranked H3. |
| Metrics | CodeSearchNet Pure H3 quality Hit@1 `0.823`, Hit@10 `0.961`, nDCG `0.900`, mean `555 ms`; IntelliJ H3 + Gemini 3.5 oracle Hit@10 `0.976` after rerank. |
| Cost/latency/index-size | Pure H3 has no ranking API call; CodeSearchNet mean query latency `555 ms`. Exact public quality index size not documented in the source reports. |
| Result summary | H3 is the fastest accepted quality baseline and exceeds the project Hit@10 target on the local positive slice. |
| Decision | Accepted as the production candidate-generator design. The concrete default is now H6.1 EmbeddingGemma calibrated hybrid. |
| Failure modes | Public positive slice is not official full-corpus MTEB; file-level metadata may dilute function-level CodeSearchNet targets; candidate recall still caps reranking. |
| Follow-ups | Add large-negative/full-corpus public profile; compare Qwen3 4B, EmbeddingGemma, Gemini, and Voyage Code with the same H3 stack. |
| Links | [current research state](../current-research-state-2026-06-04.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/benchmarks/codesearchnet-mteb-python-h5-qwen-quality.yml`, `configs/benchmarks/codesearchnet-mteb-python-pure-h3.yml` |

## H3-INTELLIJ-ORACLE - H3 Manifest Union Plus Gemini 3.5

| Field | Value |
| --- | --- |
| ID | `H3-INTELLIJ-ORACLE` |
| Status | oracle / not routine default |
| Motivation | Prove the Hit@10 target is reachable on the large internal IntelliJ answer-set evaluation. |
| Assumptions | H3 manifest candidates have enough recall and Gemini 3.5 Flash can rank broad answer-set candidates well. |
| Index composition | `configs/intellij/intellij-postrank-h3-manifest.yml`; manifest + summary hybrid union over IntelliJ. |
| Search/ranking flow | H3 manifest union top candidates -> Gemini 3.5 Flash file-first listwise rerank -> final ranked files. |
| Model/provider matrix | Vertex `gemini-3.5-flash` reranker. |
| Dataset | `datasets/intellij_eval_1000.answer_sets.jsonl`, 1,000 cases, answer sets with exact paths and `glob:` labels. |
| Metrics | Hit@1 `0.871`, Hit@3 `0.903`, Hit@5 `0.943`, Hit@10 `0.976`, Recall@10 `0.964`, Precision@10 `0.419`, MRR `0.898`, nDCG `0.908`. |
| Cost/latency/index-size | Mean `6542 ms`, p95 `9285 ms`, estimated cost `$34.94`, 22.6M tokens for 1,000 cases. |
| Result summary | The setup passed the Hit@10 target and the lower 95% CI bound was above 0.95, but the evaluation has known optimism/label-governance caveats. |
| Decision | Use as quality ceiling/oracle, not routine experiment loop. |
| Failure modes | `answer_sets` is permissive; no-glob estimate was about `0.946`; some globs matched no files in later validation; cost is high. |
| Follow-ups | Report full/no-glob/exact-only scores; add fail-fast/degraded gates; run cheaper Gemini Lite clean H3 answer-set sweep. |
| Links | [IntelliJ answer-set eval](../intellij-answer-set-eval-2026-06-03.md), [final quality conclusions](../final-search-quality-conclusions-2026-06-03.md), [eval validity review](../eval-validity-review-2026-06-03.md), `configs/intellij/intellij-postrank-h3-manifest.yml` |

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
| Links | [agentic H3 comparison](../agentic-h3-comparison-2026-06-03.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), `configs/intellij/intellij-postrank-h3-manifest.yml`, `configs/benchmarks/codesearchnet-mteb-python-h3-agentic.yml` |

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
| Links | [IntelliJ H2 postrank H3/H4 update](../intellij-postrank-h2-2026-06-02.md), [IntelliJ H2 matrix](../intellij-h2-matrix-overnight-2026-06-02.md), `configs/intellij/intellij-postrank-h2.yml` |

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
| Decision | Superseded as the default by H6.1 EmbeddingGemma static hybrid until a same-index LLM/agent rerank run beats it cleanly. Keep H5 as the active ranking experiment. |
| Failure modes | Candidate recall ceiling, prompt size for local rankers, API cost/quotas, public-slice not official full-corpus MTEB. |
| Follow-ups | Run stronger embedding models with the same H5 protocol; add a true cross-encoder reranker baseline. |
| Links | [current research state](../current-research-state-2026-06-04.md), [final report](../final-report-2026-06-03.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), `configs/benchmarks/codesearchnet-mteb-python-h5-qwen-quality.yml` |

## H6.1 - Calibrated Hybrid Candidate Weights

| Field | Value |
| --- | --- |
| ID | `H6.1` |
| Status | accepted default |
| Motivation | Replace manual H3/H5 hybrid weights with weights chosen on a train split and validated on held-out cases. |
| Assumptions | The existing hybrid signals are useful, but their relative weights should be calibrated against file-level metrics rather than hand-picked. |
| Index composition | Same file-metadata shape as `configs/benchmarks/codesearchnet-mteb-python-h5-embeddinggemma-quality.yml`: EmbeddingGemma-300M, `file_summary` + `file_manifest`, no code-body chunks. |
| Search/ranking flow | H3 candidate generation -> collect score components -> grid/linear weight sweep on train -> validate frozen weights -> use frozen H6.1 hybrid weights by default. |
| Model/provider matrix | Accepted default uses EmbeddingGemma-300M. Qwen3-Embedding-0.6B remains the control. No LLM calls during default retrieval. |
| Dataset | CodeSearchNet/MTEB Python local positive slice, 1,000 cases, split 700 train / 300 validation, seed `17`. |
| Metrics | Manual H5 validation file Hit@1 `0.837`, Hit@5 `0.947`, Hit@10 `0.960`, MRR@10 `0.888`; best calibrated candidate file Hit@1 `0.843`, Hit@5 `0.953`, Hit@10 `0.960`, MRR@10 `0.893`. |
| Cost/latency/index-size | Calibration tested 1,296 profiles in `862.6s`, including `576.5s` context collection; no API or LLM cost. |
| Result summary | Calibration gives a small head-ranking gain by itself, but the larger win came from pairing calibrated weights with EmbeddingGemma-300M. |
| Decision | Accepted as the default local candidate generator and default CLI search/evaluate profile. LLM/agent rerank must beat this same-index baseline before promotion. |
| Failure modes | Flat validation plateau, possible split overfit, route-specific weight rewrites not separately learned, graph signal may be weak because default H5 graph has limited edge types. |
| Follow-ups | Run larger 10k calibration if dataset is available; test finer/medium grid; learn route-specific profiles for `semantic`, `path_symbol`, and `workflow`. |
| Links | [default search hypothesis](../default-search-hypothesis-2026-06-05.md), [H5 hybrid weight calibration](../h5-hybrid-weight-calibration-2026-06-04.md), `.code-diver/reports/h6-2-mlp-weights-embeddinggemma-codesearchnet-1000.json`, `scripts/calibrate_hybrid_weights.py` |

## H6.2 - Learned MLP Candidate Scorer

| Field | Value |
| --- | --- |
| ID | `H6.2` |
| Status | rejected as default; active only for ranking-loss research |
| Motivation | Test whether a tiny learned scorer over hybrid features can learn non-linear interactions or per-candidate dynamic weights that fixed weighted sums miss. |
| Assumptions | Features such as vector score, lexical score, path score, symbol coverage, graph score, file vote, and item-kind weight may interact non-linearly; a 1-3 layer MLP or dynamic weight-vector predictor might improve head ranking. |
| Index composition | Pure H3 file-metadata index for the current valid 1,000-case run; H5-feature smoke reports are retained only as early checks. |
| Search/ranking flow | H3 candidate generation -> feature cache -> candidate-level binary labels from expected files -> NumPy MLP scorer. `scalar` mode predicts one candidate score; `weights` mode predicts a vector over hybrid signals and scores by weighted sum. |
| Model/provider matrix | No embedding/model changes; local NumPy MLP only. This is not a generative LLM and adds no API cost. |
| Dataset | Valid run uses CodeSearchNet/MTEB Python local positive slice, 1,000 cases, split 700 train / 300 validation, seed `17`. |
| Metrics | Qwen0.6B fresh validation: manual routed H3 file Hit@1/10 `0.757`/`0.950`, H6.2 dynamic-weight MLP `0.757`/`0.950`, H6.1 static/grid `0.770`/`0.957`. EmbeddingGemma validation: manual routed H3 file Hit@10 `0.983`, H6.2 dynamic-weight MLP `0.980`, H6.1 static/grid `0.983`; EmbeddingGemma H6.1 file Hit@1 `0.863`, MRR `0.911`. |
| Cost/latency/index-size | Training is local CPU over cached candidate features. Feature collection cost is shared with H6.1; subsequent MLP runs can use `--reuse-feature-cache`. |
| Result summary | H6.2 does not clear the requested `+0.05` threshold on either valid Qwen0.6B or EmbeddingGemma runs. H6.1 static/grid is better than H6.2, but its Qwen gain is small compared with changing the embedding model. |
| Decision | Do not use binary-loss H6.2 as the default. Keep its feature cache for pairwise/listwise ranking-loss experiments. Current default candidate generator should be EmbeddingGemma + H6.1 static/grid weights. |
| Failure modes | Candidate-level labels are imbalanced; MLP can overfit train candidates; binary candidate labels may not optimize listwise ranking; no feature cache means collection dominates runtime. |
| Follow-ups | Compare depth 0, 1, 2, 3; add route-specific training; add pairwise/listwise loss; test whether dynamic weights are useful only on low-confidence H3 cases. |
| Links | [local model axis experiments](../local-model-axis-experiments-2026-06-04.md), [H5 hybrid weight calibration](../h5-hybrid-weight-calibration-2026-06-04.md), `.code-diver/reports/h6-2-mlp-weights-pure-h3-qwen-fresh-codesearchnet-1000.json`, `.code-diver/reports/h6-2-mlp-weights-embeddinggemma-codesearchnet-1000.json`, `scripts/calibrate_hybrid_weights.py` |

## H7.1 - Compact API Manifest File Vector

| Field | Value |
| --- | --- |
| ID | `H7.1` |
| Status | active / pending eval |
| Motivation | H6.1 file summaries/manifests can dilute the specific function/API/effect that CodeSearchNet-style or informal behavior queries are asking for. Add a compact API-level file record without indexing function bodies. |
| Assumptions | Signatures, split identifier terms, call/attribute/resource terms, effect tags, symbol counts, and short doc/comment hints are enough to improve natural-language-to-file matching while keeping the persistent index small. |
| Index composition | H6.1 `file_summary` + `file_manifest` plus one new `file_api_manifest` item per file. No line chunks, structural chunks, symbol body chunks, or function-body vectors. |
| Search/ranking flow | Query -> H6.1 calibrated hybrid search over three file-level item kinds -> optional monotonic LLM/agent rerank -> final file list. |
| Model/provider matrix | First planned run keeps EmbeddingGemma-300M and the best completed local agentic setup fixed, then changes only index composition. |
| Dataset | CodeSearchNet/MTEB Python 100-case public slice first; promote to 1,000 cases only if the 100-case delta is positive and non-degraded. |
| Metrics | not measured |
| Cost/latency/index-size | Expected persistent vector count is about 1.5x H6.1 because H6.1 has two file-level vectors per file and H7.1 has three. |
| Result summary | Deterministic fusion mishandles the extra API lane, but the 26B-A4B local agent/reranker uses it to improve head ordering without improving top-10 recall. |
| Decision | Keep as an agent/reranker context feature, not the deterministic default. |
| Failure modes | Doc hints may overfit CodeSearchNet docstring-shaped queries; extra vectors can add noisy near-duplicates; local agent latency can hide retrieval gains. |
| Follow-ups | Compare deterministic H6.1 vs H7.1 first, then run the best bounded agent/reranker on the winner. Add repo-local/e2e explanation validation before default promotion. |
| Links | [H7 compact index hypotheses](../h7-compact-index-hypotheses-2026-06-06.md), `configs/benchmarks/codesearchnet-agent-axis-local-100-h7-api-manifest.yml`, `src/code_diver/services/file_api_manifest_item_builder.py` |

## H7.2 - Lexical Query Expansion Without Index Growth

| Field | Value |
| --- | --- |
| ID | `H7.2` |
| Status | active / pending eval |
| Motivation | Short developer queries and common aliases such as `db`, `auth`, `url`, `cmd`, and `stream` can collapse dense search or get filtered before BM25 can help. |
| Assumptions | Expanding only lexical terms can improve exact-match candidate recall without injecting synonym noise into vector embeddings. |
| Index composition | Same H6.1 `file_summary` + `file_manifest` artifact. No new vectors and no reindex required. |
| Search/ranking flow | Query -> original dense vector search + expanded lexical/BM25 terms -> H6.1 weighted fusion -> optional rerank/agent. |
| Model/provider matrix | Embedding model unchanged. First run should use the same EmbeddingGemma H6.1 control and no LLM rerank. |
| Dataset | CodeSearchNet/MTEB Python 100-case slice first, then larger slices if positive. |
| Metrics | Deterministic 100-case: Hit@1 `0.810`, Hit@10 `0.970`, MRR `0.867`, below H6.1 control Hit@1 `0.820`, MRR `0.876`. Agentic 26B-A4B 100-case: Hit@1 `0.730`, Hit@10 `0.900`, MRR `0.788`, below H7.1 agentic Hit@1 `0.760`, MRR `0.805`. |
| Cost/latency/index-size | No persistent index growth; only a tiny query-time lexical-term expansion cost. |
| Result summary | Global aliases reduce degraded rate in the agentic run but do not beat H7.1 on quality. |
| Decision | Do not promote as-is. Revisit only as route-specific or LLM-planned expansion. |
| Failure modes | Broad aliases can introduce false positives; aliases are global rather than route/language-specific; CodeSearchNet may not stress the same short-query pattern as real users. |
| Follow-ups | Add route-specific aliases and learned/calibrated alias weights if the first global expansion is noisy. |
| Links | [H7 compact index hypotheses](../h7-compact-index-hypotheses-2026-06-06.md), `configs/benchmarks/codesearchnet-agent-axis-local-100-h7-query-expansion.yml`, `src/code_diver/strategies/hybrid_query_expander.py` |

## H7 - Agent-Planned Probes With One Shared Rerank

| Field | Value |
| --- | --- |
| ID | `H7` |
| Status | proposed / research only |
| Motivation | Test the agent-first product shape without letting the model perform expensive open-ended repository exploration. The LLM should generate several targeted search probes, Code Diver should run bounded retrieval in parallel, and only then should the LLM rank the merged evidence pool once. |
| Assumptions | Multi-query planning can improve candidate recall for informal questions; reranking the merged pool once is cheaper and cleaner than reranking every probe independently; using a cheap probe retriever avoids multiplying LLM cost by query count. |
| Index composition | Same H6.1/H5 file-first metadata index. No code-body vectors are required for this hypothesis. |
| Search/ranking flow | User question -> LLM query planner -> 2-4 parallel bounded probe searches, usually `hybrid` -> deterministic candidate merge/dedupe -> one shared LLM rerank over the merged pool -> bounded file context reads -> answer generation. |
| Model/provider matrix | Planner/reranker can be Gemini 3.1 Flash Lite, Qwen3.5 4B, Gemma E2B/E4B, or other configured generation providers. Embeddings remain whatever the active index uses. |
| Dataset | Start with SWE-QA-Pro/Qibo E2E smoke, then compare on larger SWE-QA-Pro slices once the answer dataset is stable. |
| Metrics | Required: candidate/context file Hit@1/3/5/K, candidate/context recall and precision, answer token/key-token/bigram F1, judge metrics where enabled, `planned_query_count`, `planning_duration_ms`, `rerank_duration_ms`, total latency, model calls, tokens, estimated cost, degraded/error count. |
| Cost/latency/index-size | Reuses the same index. Adds one query-planning model call and optionally one shared rerank model call. Probe searches can run in parallel, but total retrieval latency still includes planner + probes + final rerank. |
| Result summary | Not accepted yet. The first `--agentic-queries` smoke without shared rerank stayed flat on recall and was slower than single-query retrieval on the 3-case Qibo slice. H7 exists to test the cleaner variant explicitly instead of treating that smoke as the final agentic answer. |
| Decision | Not default. Promote only if it improves file/context recall or answer judge score enough to justify planner/rerank latency on the same cases. Reject if it only reshuffles candidates while adding cost. |
| Failure modes | Query probes can collapse to the same intent; a weak deterministic merge can bury the right candidate before rerank; shared rerank can overfit previews; planner/reranker using the same model family as answer generation can hide correlated failures. |
| Follow-ups | Add diversity constraints to query planning; compare `hybrid` probe search against `hybrid_rerank` probe search; test one final rerank versus no final rerank; add a full Branch A inspector with outline/symbol/rg/read tools after candidate selection. |
| Links | [E2E answer evaluation](../e2e-answer-eval-2026-06-05.md), `uv run code-diver --help-all evaluate-answers --agentic-queries --agentic-query-search-strategy hybrid --agentic-query-rerank` |

## H8 - Calibrated Reranker Ensemble

| Field | Value |
| --- | --- |
| ID | `H8` |
| Status | active research |
| Motivation | Test whether several rankers can be combined like hybrid retrieval signals, with a learned meta-ranker deciding when to trust deterministic H6/H7 outputs versus LLM/agentic reranker outputs. |
| Assumptions | Different rankers make different errors; saved per-candidate rank positions contain enough signal for a small calibrated model to improve top-k quality without reading code bodies or increasing persistent index size. |
| Index composition | Same H6.1/H5 file-first metadata index. H8 changes only the final ranking layer over candidate file rankings. |
| Search/ranking flow | H6/H7 candidate rankings and optional LLM/agent rankings -> candidate union -> per-candidate rank features -> calibrated meta-ranker -> final file ranking. |
| Model/provider matrix | Offline test used saved deterministic H6/H7 rankings plus local Gemma E2B/E4B/12B/26B-A4B agentic rankings. Future tests should swap one reranker axis at a time: Gemini Lite, Qwen3-Reranker, Gemma 26B-A4B. |
| Dataset | Saved 100-case CodeSearchNet/MTEB Python slice; 1,000-case CodeSearchNet/MTEB Python slice with 900 train / 100 held-out test; 750/150/100 sweep for validation-selected calibration. The 1,000-case slice is entirely single-positive (`expected_files_distribution={"1":1000}`), so Hit@K equals Recall@K and Precision@10 has a hard useful ceiling of 0.1 for successful cases. |
| Metrics | 100-case diverse-ranker CV: best single `h6` Hit@1 `0.820`, Hit@10 `0.970`, nDCG `0.900`; logistic stacking improved to Hit@1 `0.840`, Hit@10 `0.980`, nDCG `0.918`. 1,000-case Gemini Lite full run: Hit@1 `0.911`, Hit@3 `0.978`, Hit@5 `0.988`, Hit@10 `0.989`, MRR `0.944`, nDCG `0.956`. 900/100 held-out: single Gemini Lite Hit@1 `0.960`, Hit@10 `1.000`, nDCG `0.983`; best learned pairwise deterministic+Gemini stack Hit@1 `0.950`, Hit@10 `1.000`, nDCG `0.979`; oracle deterministic+Gemini Hit@1 `0.980`. |
| Cost/latency/index-size | Offline analysis has no model-call cost. Live use must not run many LLM agents by default; production H8 should combine cheap deterministic rank signals and at most one optional LLM/cross-encoder signal. |
| Result summary | The ensemble idea has headroom, but rank-position-only calibration cannot beat the current best single reranker, Gemini 3.1 Flash Lite. Equal-weight RRF, weighted RRF, pointwise stacking, pairwise stacking, and Gemini-anchor override guards all fail to improve on Gemini Lite on the held-out tail. Hit@5/Hit@10 are saturated on this single-positive slice; MRR/nDCG/mean rank are the meaningful differentiators. |
| Decision | Active research, not default. Default should remain H6.1 candidates plus one Gemini Lite rerank when quality mode is enabled. H8 needs richer score/confidence features or a true cross-encoder before promotion. |
| Failure modes | 100-case overfitting, final-ranking-only features instead of raw score logits, correlated ranker errors, and impractical live cost if multiple LLM rankers are called per user query. |
| Follow-ups | Train on raw candidate-level H6/H7/LLM features: LLM confidence/reason, hybrid score margins, route/query bucket, deterministic top1/top2 margin, and true cross-encoder scores. Test Qwen3-Reranker as the cheap second signal. Add a multi-positive/e2e explanation benchmark because this single-positive slice cannot measure product precision/recall well. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `scripts/analyze_reranker_ensemble.py`, `.code-diver/reports/reranker-ensemble-all-saved-codesearchnet-100.json` |

## H8.1 - Plain RRF Reranker Ensemble

| Field | Value |
| --- | --- |
| ID | `H8.1` |
| Status | rejected as default |
| Motivation | Check whether rankers can be combined with the standard no-training Reciprocal Rank Fusion baseline. |
| Assumptions | Rankers are complementary and equal confidence is good enough. |
| Index composition | Same H6.1/H5 file-first metadata index; no new persistent index. |
| Search/ranking flow | Multiple saved file rankings -> equal-weight RRF -> final file ranking. |
| Model/provider matrix | Tested deterministic H6/H7 rankings, plus the 100-case saved local Gemma agent rankings in the first offline run. |
| Dataset | CodeSearchNet/MTEB Python 100-case offline run; 1,000-case deterministic reports with 900 train / 100 test. |
| Metrics | 100-case best RRF matched H6.1 Hit@1 `0.820`, Hit@10 `0.970`, nDCG `0.900`. 900/100 deterministic-only RRF Hit@1 `0.930`, Hit@10 `1.000`, nDCG `0.967`, below best single `h7_query_expansion` Hit@1 `0.940`, nDCG `0.969`. 900/100 deterministic+Gemini best RRF Hit@1 `0.950`, Hit@10 `1.000`, nDCG `0.977`, below single Gemini Lite Hit@1 `0.960`, nDCG `0.983`. |
| Cost/latency/index-size | Essentially free offline/live after input rankings exist. |
| Result summary | RRF is a useful sanity baseline but not a quality improvement here. |
| Decision | Reject as default. |
| Failure modes | Equal weights let weaker/noisier rankers demote strong deterministic top hits. |
| Follow-ups | Keep only as a baseline row in H8 experiments. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `scripts/analyze_reranker_ensemble.py` |

## H8.2 - Weighted RRF Reranker Ensemble

| Field | Value |
| --- | --- |
| ID | `H8.2` |
| Status | rejected as default |
| Motivation | Test whether a calibrated weight vector over rankers is enough, without a learned candidate-level model. |
| Assumptions | One global ranker-weight vector generalizes across queries. |
| Index composition | Same H6.1/H5 file-first metadata index; no new persistent index. |
| Search/ranking flow | Multiple saved file rankings -> train RRF weights on labeled cases -> apply weighted RRF on held-out cases. |
| Model/provider matrix | Tested deterministic H6/H7 reports on the 1,000-case slice. |
| Dataset | CodeSearchNet/MTEB Python 1,000-case deterministic reports; first 900 train, next 100 test. |
| Metrics | Deterministic-only learned weights `h6=0.25`, `h7_tiebreak=0.50`, `h7_query_expansion=0.25`; held-out Hit@1 `0.920`, Hit@10 `1.000`, nDCG `0.962`, below best single. Deterministic+Gemini weighted RRF Hit@1 `0.950`, Hit@10 `1.000`, nDCG `0.978`, below single Gemini Lite. |
| Cost/latency/index-size | Free after input rankings exist; training is a small grid search. |
| Result summary | Global weighted RRF overfit/demoted the best single ranker on the held-out tail. |
| Decision | Reject as default. |
| Failure modes | A single global weight vector cannot adapt to query buckets or confidence margins. |
| Follow-ups | If revisited, use per-query route/bucket features rather than one global vector. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `.code-diver/reports/h8-reranker-ensemble-train900-test100-deterministic.json` |

## H8.3 - Logistic Stacking Meta-Ranker

| Field | Value |
| --- | --- |
| ID | `H8.3` |
| Status | active research |
| Motivation | Learn when to trust each ranker using candidate-level rank features, not just a global ranker weight. |
| Assumptions | Rank positions, agreement, and top-1 flags expose enough signal for a tiny supervised model to choose better candidates. |
| Index composition | Same H6.1/H5 file-first metadata index; no new persistent index. |
| Search/ranking flow | Candidate union -> reciprocal-rank / normalized-rank / top-1 / agreement features -> logistic scoring model -> final file ranking. |
| Model/provider matrix | 100-case run used deterministic H6/H7 plus Gemma E2B/E4B/12B/26B-A4B agent outputs. 1,000-case follow-up used deterministic H6/H7, then deterministic H6/H7 plus Gemini Lite. |
| Dataset | CodeSearchNet/MTEB Python 100-case 5-fold CV; 1,000-case reports with 900 train / 100 test; 750/150/100 validation-selected sweep. |
| Metrics | 100-case diverse-ranker CV improved best single Hit@1 `0.820` -> `0.840`, Hit@10 `0.970` -> `0.980`, nDCG `0.900` -> `0.918`. 900/100 deterministic-only test scored Hit@1 `0.930`, Hit@10 `1.000`, nDCG `0.967`, below best single `h7_query_expansion`. 900/100 deterministic+Gemini pointwise stack scored Hit@1 `0.940`, Hit@10 `1.000`, nDCG `0.975`, below single Gemini Lite. 750/150/100 validation-selected pointwise stack scored test Hit@1 `0.950`, Hit@10 `1.000`, nDCG `0.979`, still below Gemini Lite. |
| Cost/latency/index-size | Training is cheap; live cost depends entirely on how many input rankers are executed. |
| Result summary | Works on the small diverse 100-case slice, but fails to beat the best single Gemini Lite reranker on the larger held-out split. |
| Decision | Active research. Do not promote rank-position-only H8.3. |
| Failure modes | Overfitting on small splits, correlated ranker errors, final-rank-only features instead of raw scores/logits. |
| Follow-ups | Add raw score, confidence, margin, and route features; compare against H8.4 pairwise and Qwen3-Reranker. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `scripts/analyze_reranker_ensemble.py` |

## H8.4 - Pairwise Logistic Meta-Ranker

| Field | Value |
| --- | --- |
| ID | `H8.4` |
| Status | active research; rejected as current default |
| Motivation | Optimize ranking order directly with positive-vs-negative candidate pairs instead of binary pointwise labels. |
| Assumptions | Pairwise loss should better align with Hit@K/MRR than candidate-level classification. |
| Index composition | Same H6.1/H5 file-first metadata index; no new persistent index. |
| Search/ranking flow | Candidate union -> rank-position features -> pairwise logistic training -> final file ranking. |
| Model/provider matrix | Tested deterministic H6/H7 plus Gemini 3.1 Flash Lite. |
| Dataset | CodeSearchNet/MTEB Python 1,000-case reports, first 900 train / next 100 test. |
| Metrics | Deterministic-only Hit@1 `0.930`, Hit@10 `1.000`, nDCG `0.967`. Deterministic+Gemini Hit@1 `0.950`, Hit@3 `0.990`, Hit@5 `1.000`, Hit@10 `1.000`, MRR `0.972`, nDCG `0.979`. Single Gemini Lite on the same test scored Hit@1 `0.960`, MRR `0.978`, nDCG `0.983`. |
| Cost/latency/index-size | Offline training is local and cheap. Live cost is unchanged versus the input rankers. |
| Result summary | Best learned H8 variant so far, but still below single Gemini Lite with rank-position-only features. |
| Decision | Do not use as default. Keep as the next calibration baseline after richer features are added. |
| Failure modes | Pairwise model cannot infer when Gemini is wrong without confidence/raw-score features; correlated deterministic runs add little new evidence. |
| Follow-ups | Add LLM confidence/reason, raw hybrid score margins, and true cross-encoder scores. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `.code-diver/reports/h8-reranker-ensemble-train900-test100-gemini-lite.json` |

## H8.5 - Gemini-Anchor Override Guard

| Field | Value |
| --- | --- |
| ID | `H8.5` |
| Status | rejected as active override; keep as safety diagnostic |
| Motivation | Preserve the strong Gemini Lite ordering and only let deterministic rankers override it when agreement/margin rules suggest a safe fix. |
| Assumptions | A small rule guard can capture the rare cases where deterministic rankers are right and Gemini demotes the expected file. |
| Index composition | Same H6.1/H5 file-first metadata index; no new persistent index. |
| Search/ranking flow | Gemini Lite ranking -> optional deterministic top-file promotion based on validation-selected rules. |
| Model/provider matrix | Gemini 3.1 Flash Lite plus deterministic H6/H7 rankers. |
| Dataset | CodeSearchNet/MTEB Python 1,000-case reports, 750 train / 150 validation / 100 test. |
| Metrics | Best validation-selected rule was effectively a no-op: final test Hit@1 `0.960`, Hit@10 `1.000`, MRR `0.978`, nDCG `0.983`, identical to Gemini Lite. More aggressive overrides fixed some cases but broke more on train/validation. |
| Cost/latency/index-size | Free after input rankings exist. |
| Result summary | Rank-position-only deterministic override is not safe. |
| Decision | Do not enable active overrides. Use the no-op outcome as evidence that Gemini Lite should remain the anchor until richer confidence features exist. |
| Failure modes | Deterministic agreement is not a reliable confidence estimate; rules overfit rare misses. |
| Follow-ups | Retry only with Gemini confidence, deterministic score margins, and query route/bucket features. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `.code-diver/reports/h8-gemini-anchor-override-guard-train750-val150-test100.json` |

## H8-ORACLE - Best-Rank Upper Bound

| Field | Value |
| --- | --- |
| ID | `H8-ORACLE` |
| Status | oracle / diagnostic only |
| Motivation | Estimate the maximum possible quality if a perfect meta-ranker could always pick the best available ranker output. |
| Assumptions | None for production; this intentionally uses labels and is therefore not deployable. |
| Index composition | Same as the input ranker reports. |
| Search/ranking flow | For each case, inspect all ranker outputs and choose the best rank of a known relevant file. |
| Model/provider matrix | Same as the input ranker reports. |
| Dataset | CodeSearchNet/MTEB Python saved reports. |
| Metrics | 100-case deterministic + agentic oracle: Hit@1 `0.940`, Hit@10 `0.990`. 900/100 deterministic-only oracle: Hit@1 `0.940`, Hit@5 `0.990`, Hit@10 `1.000`. 900/100 deterministic+Gemini oracle: Hit@1 `0.980`, Hit@3 `0.990`, Hit@5 `1.000`, Hit@10 `1.000`. |
| Cost/latency/index-size | Not applicable; cannot run without labels. |
| Result summary | There is theoretical Hit@1 headroom after adding Gemini, but the production model needs richer features to identify the two held-out cases where deterministic rankers beat Gemini. |
| Decision | Use only as upper-bound evidence. Never report as product quality. |
| Failure modes | Label leakage by definition. |
| Follow-ups | Compare oracle gap before and after adding a genuinely different reranker family. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `.code-diver/reports/h8-reranker-ensemble-train900-test100-deterministic.json` |

## H9 - Semantic Hard-Case Evidence Layer

| Field | Value |
| --- | --- |
| ID | `H9` |
| Status | proposed |
| Motivation | H8 analysis showed that repeated Hit@5/Hit@10 values come from a single-positive benchmark with saturated top-10 recall, while remaining Gemini Lite misses concentrate in semantic queries where evidence lives in comments, string literals, constants, or implementation behavior. |
| Assumptions | H6.1/H8 file-level summaries/manifests are too compact for some CodeSearchNet-style semantic queries. Adding a compact body-evidence lane can improve candidate recall without indexing full code chunks. |
| Index composition | Existing H6.1 `file_summary` + `file_manifest`, plus a proposed `file_body_evidence` item containing comments, string literals, key calls, return/raise expressions, exception messages, HTTP/resource strings, and docstring-derived phrases. No full method body vectors by default. |
| Search/ranking flow | Query -> H6.1/H8 candidate generation -> if semantic/low-confidence, merge a body-evidence search lane -> Gemini Lite or cross-encoder rerank -> final files. |
| Model/provider matrix | Keep EmbeddingGemma and Gemini Lite fixed initially. Test Qwen3-Reranker/cross-encoder as the cheap rerank feature after candidate recall improves. |
| Dataset | CodeSearchNet/MTEB Python 1,000-case slice first, with focus on Gemini Lite miss/not-top cases; then a multi-positive/e2e explanation benchmark because single-positive CodeSearchNet cannot measure real product precision/recall well. |
| Metrics | For CodeSearchNet: Hit@1, MRR, nDCG, rank distribution, semantic-bucket Hit@1/10, and miss count. Do not optimize on Precision@10 for this slice because its successful-case ceiling is 0.1. For e2e: context-file precision/recall, answer judge score, and token/cost metrics. |
| Result summary | Not tested yet. Error analysis suggests candidate generation, not rank fusion, is now the main limiter for the residual misses. |
| Decision | Proposed next research direction. Implement only as a bounded extra evidence lane, not a return to full code-body indexing. |
| Failure modes | Extra vectors may add noisy body matches and hurt top1; comments/constants can overfit CodeSearchNet docstring-shaped queries; route gating may miss hard path/symbol cases. |
| Follow-ups | Build `file_body_evidence` extractor; run H9.1 all-cases and H9.2 semantic-gated variants; compare against H8 Gemini Lite on the same fixed reports. |
| Links | [reranker ensemble report](../reranker-ensemble-2026-06-07.md), `configs/benchmarks/codesearchnet-h8-gemini-lite-rerank-1000.yml` |

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
| Result summary | Current best measured local candidate generator is EmbeddingGemma-300M + H6.1 static/grid weights. Current agent-axis smoke over that generator: Gemini Lite 25 cases Hit@10 `0.920`, mean `11,320 ms`, cost `$0.206`; Qwen3.5 4B 10 cases Hit@10 `1.000`, mean `37,020 ms`; Gemma 4 E4B 10 cases Hit@10 `0.900`, mean `56,573 ms`; Gemma 4 12B Q4_K_M stalled before completing a case. |
| Decision | Active. Every new local-model claim must name which axis changed and which two axes were fixed. Promote Qwen3.5 4B and Gemini Lite to larger same-case agent comparison; do not promote Gemma 12B until runtime isolation is fixed. |
| Failure modes | Mixed-axis runs cannot identify causality; local serving failures can masquerade as model quality; agentic loops can over-search and spend latency without improving recall; Vertex/API auth or API-version errors can silently corrupt metrics if reports are not marked invalid. |
| Follow-ups | Add run manifests with axis labels; add report grouping by changed axis; run Qwen3 4B embedding once local serving is stable; test Qwen3-Reranker through a real rerank endpoint; add hard wall-clock/tool-call caps to agent eval. |
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
| Model/provider matrix | Current practical default EmbeddingGemma-300M; candidates include Qwen3-Embedding-4B, Gemini Embedding, Voyage Code 3, Jina code embeddings, Codestral Embed. |
| Dataset | Next matrix should use CodeSearchNet local positive slice and larger-negative/full-corpus public profile when available. |
| Metrics | H6 validation: Qwen0.6B best static/grid file Hit@1/10 `0.770`/`0.957`; EmbeddingGemma-300M best static/grid file Hit@1/10 `0.863`/`0.983`. 100-case same-stack smoke: Qwen0.6B file Hit@1/10 `0.750`/`0.950`, EmbeddingGemma-300M file Hit@1/10 `0.810`/`0.950`. Public MTEB extract lists Qwen3-Embedding-0.6B official score `0.94325`, Qwen3-Embedding-4B `0.96004`, EmbeddingGemma-300m `0.96180`, Gemini embedding `0.96495`, Voyage Code 3 `0.96688`. |
| Cost/latency/index-size | Qwen 0.6B is already integrated and fast enough; larger/API models have unmeasured Code Diver cost in the same stack. |
| Result summary | EmbeddingGemma-300M is the best measured local embedding model so far in the same H3/H6 stack. Qwen 0.6B remains useful as a fast runtime baseline. |
| Decision | Promote EmbeddingGemma-300M to the next reranker/agent experiments; keep Qwen 0.6B as the control. Qwen3-Embedding-4B is still pending. |
| Failure modes | Official MTEB scores are not directly comparable to Code Diver local positive-slice metrics; API models add cost/quota; gated licenses may block local setup. |
| Follow-ups | Add run manifests with model/provider versions, config hashes, index hashes, and dataset hashes. |
| Links | [local model axis experiments](../local-model-axis-experiments-2026-06-04.md), [code embedding model research](../code-embedding-model-research-2026-06-04.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/benchmarks/codesearchnet-mteb-python-h5-qwen-quality.yml` |

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
| Links | [local model axis experiments](../local-model-axis-experiments-2026-06-04.md), [top-5 hypotheses eval](../top5-hypotheses-eval-2026-06-02.md), [final quality conclusions](../final-search-quality-conclusions-2026-06-03.md), [eval validity review](../eval-validity-review-2026-06-03.md), `configs/intellij/intellij-postrank-h3-manifest.yml` |

## PUBLIC-BENCH - Lightweight Public Retrieval Benchmarks

| Field | Value |
| --- | --- |
| ID | `PUBLIC-BENCH` |
| Status | active internal benchmark, not official SOTA |
| Motivation | Provide a reviewer-runnable public benchmark path instead of relying on a sibling/private repo or IntelliJ-only internal data. |
| Assumptions | A local positive slice is useful for comparing Code Diver architectures quickly, even though it is not the official full-corpus protocol. |
| Index composition | Materialized positive qrel files from `mteb/CodeSearchNetRetrieval` and a 100-qrel `mteb/SWEbenchCodeRetrieval` smoke slice. Current quality profile uses EmbeddingGemma-300M file metadata. |
| Search/ranking flow | H6.1 calibrated hybrid candidate generation; optional H8/H5 reranking for Python reference rows. |
| Model/provider matrix | H6.1 local no-ranker; H8 Gemini Lite Python reference; historical local Gemma E4B rerank comparison. |
| Dataset | CodeSearchNet/MTEB Python 1,000 plus 100-case JavaScript/Java/Go/PHP/Ruby slices; SWEbenchCodeRetrieval 100 qrels / 71 files smoke slice. |
| Metrics | CodeSearchNet H6 local Hit@10: Python `0.987`, JavaScript `0.960`, Java `1.000`, Go `0.990`, PHP `0.870`, Ruby `0.990`. SWEbenchCodeRetrieval H6 local: Hit@1 `0.610`, Hit@5 `0.960`, Hit@10 `0.960`, MRR `0.752`, nDCG `0.804`. Python H8 Gemini Lite reference: Hit@1 `0.911`, Hit@10 `0.989`, nDCG `0.956`. |
| Cost/latency/index-size | New language/SWE rows are local-only and API-free. Timings are not strict performance numbers because the sweep was run in parallel and loaded local model weights multiple times. |
| Result summary | H6.1 local generalizes well to Java/Go/Ruby and moderately to JavaScript, weakly to PHP. SWEbenchCodeRetrieval is harder at Hit@1 but has high Hit@5/10, making it a better reranker/agent benchmark than single-positive CodeSearchNet. |
| Decision | Keep as current public comparison harness; do not use as official SOTA claim. |
| Failure modes | No large negative pool, not official scorer, synthetic file materialization, mostly single-positive label shape. SWEbench smoke uses only selected positive files for speed, so it is not full-corpus difficulty. |
| Follow-ups | Add first-class benchmark profiles for the new slices; add 20k/50k large-negative profiles and/or official-compatible scorer export; add CoIR and CodeXGLUE/CoSQA adapters. |
| Links | [public benchmark sweep](../public-benchmark-sweep-2026-06-07.md), [current research state](../current-research-state-2026-06-04.md), [CodeSearchNet agentic/model eval](../codesearchnet-agentic-model-eval-2026-06-04.md), [market comparison](../codesearchnet-market-comparison-2026-06-03.md), `configs/benchmarks/codesearchnet-mteb-python-h5-qwen-quality.yml` |

## H9 - Body-Evidence File Lane And Reranker Ensemble

| Field | Value |
| --- | --- |
| ID | `H9` |
| Status | rejected as always-on default; keep as gated research lane |
| Motivation | Test whether a third compact file-level index over body evidence can add complementary signal to H6/H7 and improve weighted/meta reranker ensembles. |
| Assumptions | Comments, string literals, return/raise/control lines, and effect-heavy lines can bridge natural-language queries that file summaries/manifests miss, without embedding full code bodies. |
| Index composition | H6.1 `file_summary` + `file_manifest` plus one `file_body_evidence` item per file. No line chunks, full code-body vectors, or symbol body chunks. |
| Search/ranking flow | H9 direct hybrid search; H9 bounded hybrid search; offline RRF/weighted/meta-ranker over H6/H7/H9; repeated with saved Gemini Lite ranker. |
| Model/provider matrix | Local EmbeddingGemma-300M embeddings. Gemini Lite appears only as a saved ranker report in the ensemble analysis; no new API calls. |
| Dataset | CodeSearchNet/MTEB Python 1,000 with train 900 / held-out 100 ensemble split; SWEbenchCodeRetrieval 100 smoke. |
| Metrics | CodeSearchNet H9.1 Hit@1 `0.853`, Hit@10 `0.985`, nDCG `0.927`; H9.2 bounded Hit@1 `0.860`, Hit@10 `0.986`, nDCG `0.930`. H9.2 improves 34 cases, worsens 23, same 943 versus H7 query expansion. Held-out ensemble with H9 scores Hit@1 `0.920`, below best single H7 query expansion `0.940`; with Gemini Lite, meta-ranker scores Hit@1 `0.950`, below single Gemini Lite `0.960`. SWEbench H9 Hit@1 `0.610`, Hit@10 `0.940`, below H6 Hit@10 `0.960`. |
| Cost/latency/index-size | Adds one item per file: 3,000 records for 1,000 CodeSearchNet files. Direct H9 search mean is about `1.6s/query` in the local run. |
| Result summary | Body evidence has sparse complementary signal but current global fusion and rank-position-only meta-rankers cannot exploit it safely. It improves some individual cases but degrades enough others to lose aggregate top-k quality. |
| Decision | Do not promote. Keep `file_body_evidence_chunks` and H9 configs for gated fallback experiments. |
| Failure modes | Extra lane introduces noisy lexical/body hints; rank-only ensemble lacks score/confidence/margin features; direct fusion executes the third lane for every query even when H6/H7 is already confident. |
| Follow-ups | Gate body-evidence by route and low confidence; add raw hybrid score margins, item-kind margins, LLM confidence, and cross-encoder scores to the learned reranker. |
| Links | [H9 body evidence report](../h9-body-evidence-ensemble-2026-06-07.md), `src/code_diver/services/file_body_evidence_item_builder.py`, `configs/benchmarks/codesearchnet-h9-body-evidence-bounded-embeddinggemma-1000.yml` |
