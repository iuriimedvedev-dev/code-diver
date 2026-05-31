# Tool Effectiveness Research

Date: 2026-05-31

Goal: decide where each retrieval tool should be used in a hybrid code-search pipeline.

## Current Evidence

Local deterministic retrieval on `datasets/protogen_eval_100.jsonl`:

| Strategy | Strength | Weakness |
| --- | --- | --- |
| `vector_qdrant` | Fast semantic recall: `file_hit@10=0.88`, ~31ms/query after the 9230-item hybrid reindex. | Low first-rank quality: `hit@1=0.29`, `file_precision@R=0.525`. |
| `hybrid_candidates_no_llm` | Best current file cleanliness: `file_precision@R=0.570`. | Slower: ~131ms/query; `file_hit@10=0.89` after summaries were added. |
| `hybrid_candidates_routed` | Better coverage than no-router hybrid: `file_hit@10=0.90`, `file_recall@10=0.765`, `hit@3=0.51`. | Lower file cleanliness: `file_precision@R=0.530`. |
| `hybrid_candidates_multi_index_guarded` | Best current file MRR/MAP after hybrid indexing: `file_mrr@10=0.750`, `map@10=0.620`; confirms summaries need downweighting. | Worse `hit@3=0.46`; guarded summaries help rank stability but not first-screen hit. |
| `hybrid_candidates_multi_index_routed` | Tests naive three-index boosting. | Bad top-rank result: `hit@1=0.21`, `hit@3=0.43`; file summaries become noise when boosted directly. |
| `recursive_qdrant` | Slightly higher chunk precision than vector. | Worse hit/MRR/recall and ~4x slower than vector. |

Direct Gemini tool-loop experiments on the 10-case smoke dataset showed the opposite pattern: giving the orchestrator more raw tools was worse than a structured candidate tool. `search+rg`, `search+symbols`, `search+inspect`, and `read` variants increased tokens, latency, and errors without beating `ai_search_vector_only`.

## Tool Matrix

| Tool or signal | Best cases | Bad cases | How to use |
| --- | --- | --- | --- |
| Dense vector search | Informal semantic queries: "where is authorization", "where are sessions persisted", "where does pipeline execution happen". | Exact identifiers, package names, CLI flags, filenames, config values. | Always run as a first-stage candidate generator. Keep top 50-100. |
| BM25 / lexical index | Exact terms, identifiers, error names, config keys, route names, package scripts, file names. | Vague conceptual queries with synonyms not present in code. | Run in parallel with vector and fuse with RRF. Do not let the LLM invent broad regex loops. |
| `rg` raw regex | Known symbol/string searches, debugging with a concrete term, checking whether an exact phrase exists. | Informal "where is X handled" queries. The model guesses anchors poorly and burns rounds. | Keep as an interactive diagnostic and fallback, not as the primary retrieval loop. |
| Symbol index | Class/function/interface lookup, "where is Foo implemented", locating command or strategy classes. | Workflows spread across small functions; config/docs; queries without names. | Use as structured metadata and path/symbol boost; avoid symbol-only search as default. |
| Tree/path index | Repository map, path-aware queries, package/config/docker/frontend questions. | Deep behavior questions. | Use for query routing and path boosts; cheap prefilter for config/package/docker cases. |
| Graph edges | "where is this called/run/created/registered", architecture tracing, cross-file workflows. | Single-file exact lookup; stale or too-broad graphs. | Use query-aware graph profiles. Build call/reference edges incrementally or with hard budgets. |
| Read excerpts | Verifying top candidates, reranking evidence, final answer citations. | Exploratory search. Previous evals show free reads hurt cost and quality. | Only read top 3-5 ranges after deterministic candidate generation. |
| LLM reranker | Ambiguous informal queries after vector+BM25+graph candidate generation. | Simple exact lookup; tight latency mode. | One bounded listwise call over top 20 candidates. Never open-ended multi-round search by default. |

## Hybrid Index Types

`code-diver index` can now persist three item types into the same vector store:

| Index kind | Best cases | Current evidence |
| --- | --- | --- |
| `chunk` | Evidence snippets, broad semantic matches, final answer context. | After the 9230-item reindex, chunks produced about 44-47% of first relevant hits depending on fusion. |
| `symbol` | Class/function/method, command, handler, service, model, strategy, and API queries. | Symbols produced about 53-56% of first relevant hits in the best guarded/routed runs. This is the strongest structural item type right now. |
| `file_summary` | File-level recall and reranker context. | Naive boosting hurt ranking. In `hybrid_candidates_multi_index_routed`, summaries were only 2.2% of first relevant hits but still moved noise upward. Guarded downweighting recovered rank quality. |

Current conclusion: keep all three index types, but do not let `file_summary` dominate first-stage ranking. Use summaries as a recall/rerank feature and use symbols as primary structural evidence.

## Query Routing Rules

These rules should become deterministic router features, not hardcoded repository names.

| Query shape | Route |
| --- | --- |
| Contains path-like token, extension, package file, docker/compose, pyproject/package/npm words | Tree/path + BM25 first, vector second. |
| Contains CamelCase, snake_case, function/class/interface words, or quoted identifier | Symbol + BM25 first, vector second. |
| Contains "called", "caller", "run", "created", "registered", "dispatch", "handler", "strategy", "workflow" | Vector + BM25, then query-aware graph expansion. |
| Contains "where is/where are" plus broad domain words | Vector first, BM25 second, optional reranker. |
| Top vector/BM25 candidates disagree strongly | Use one-shot reranker or verification reads. |
| Top candidates are many chunks from one file | File aggregation/dedup before final top-k. |

## BM25/RRF Follow-Up

Global BM25/RRF was tested after file-level metrics were added:

| Strategy | File Hit@10 | File MRR@10 | File Precision@R | File Recall@10 | Read |
| --- | ---: | ---: | ---: | ---: | --- |
| `hybrid_candidates_no_llm` | 0.90 | 0.753 | 0.575 | 0.755 | Best current rank quality. |
| `hybrid_candidates_bm25_rrf` | 0.91 | 0.716 | 0.505 | 0.770 | Better coverage, poor first-rank quality. |
| `hybrid_candidates_bm25_weighted` | 0.91 | 0.721 | 0.520 | 0.775 | Coverage win, still weaker ranking. |
| `hybrid_candidates_bm25_rrf_vector` | 0.92 | 0.738 | 0.540 | 0.770 | Best coverage, not enough rank quality. |

Conclusion: BM25 is useful, but global BM25 weighting is too blunt. It finds additional relevant files, then drags noisy lexical matches above semantically better candidates. The next implementation should be a router:

- exact/path/symbol/config queries: strong BM25/path/symbol weighting;
- informal semantic queries: vector/hybrid coverage weighting;
- workflow queries: vector first, then graph expansion;
- disagreement cases: one-shot reranker.

## Router V1 Result

`tool_router_v1` was implemented as `hybrid_candidates_routed`. The router chooses a weight profile from query shape:

- path/config/package queries get BM25 + path weighting;
- symbol/identifier queries get BM25 + symbol/path weighting;
- workflow queries such as created, dispatched, registered, routed, run, strategy, pipeline, and orchestrated get deeper graph expansion;
- broad semantic queries keep the baseline hybrid weights.

The first 100-case run shows that query routing is better than applying BM25 globally, but it is not tuned enough to replace the best baseline hybrid profile.

| Strategy | Hit@1 | Hit@3 | File Hit@10 | File MRR@10 | File Precision@R | File Recall@10 | nDCG@10 | MAP@10 | Mean/query | Read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `hybrid_candidates_no_llm` | 0.28 | 0.53 | 0.90 | 0.753 | 0.575 | 0.755 | 0.692 | 0.627 | 119ms | Best rank cleanliness. |
| `hybrid_candidates_graph_boost` | 0.30 | 0.53 | 0.90 | 0.747 | 0.545 | 0.755 | 0.685 | 0.616 | 121ms | Best `hit@1`, worse file ranking. |
| `hybrid_candidates_bm25_rrf_vector` | 0.15 | 0.45 | 0.92 | 0.738 | 0.540 | 0.770 | 0.684 | 0.611 | 129ms | Best coverage, weak first ranks. |
| `hybrid_candidates_routed` | 0.30 | 0.52 | 0.91 | 0.753 | 0.540 | 0.770 | 0.694 | 0.624 | 125ms | Best nDCG and good coverage/rank tradeoff. |

Router diagnosis:

- The current router splits the 100-case dataset into 39 workflow cases, 31 path/symbol cases, and 30 semantic cases.
- The router recovers most of the baseline hybrid rank quality while keeping BM25-like coverage gains.
- It beats every global BM25 profile on `hit@1`, `hit@3`, `file_mrr@10`, `ndcg@10`, and `map@10`.
- It still gives up `file_precision@R` versus `hybrid_candidates_no_llm`, which means some path/symbol/workflow triggers are still too broad.
- The next measurement should log the selected route per case and report metrics by route bucket. Without bucket metrics we can see the average tradeoff, but not which rule caused the win or regression.

## Bucket Pattern After Hybrid Indexing

After adding file summaries and route-bucket metrics, the 100-case dataset shows a concrete pattern:

| Bucket | Best current behavior | Practical route |
| --- | --- | --- |
| `semantic` | `vector_qdrant` has the best file MRR: 0.797. | Dense vector first. Add lexical/symbol only as low-weight recall signals. |
| `path_symbol` | Routed/guarded hybrid reaches about 0.790 file MRR and 0.903 file hit. | BM25/path/symbol boosted route. |
| `workflow` | Baseline/guarded hybrid is best at about 0.708 file MRR. Graph boost is not yet a win. | Vector + symbol first, then improve graph before trusting graph expansion. |

This confirms the hybrid approach, but also shows the rule: different tools should own different query buckets. A single global fusion weight is not enough.

## Research Alignment

Current 2026 practice is consistent across papers and products:

- Hybrid BM25 + dense retrieval with Reciprocal Rank Fusion is the default baseline for production RAG.
- Rerankers help when the first-stage retriever has high recall but weak ordering.
- Code search benefits from structure-aware chunks, symbol/API items, and repository graphs.
- Raw grep is still valuable for exact terms, but agent-controlled grep loops are inefficient for vague semantic queries.
- Tool routing should be observable: log which signals fired, which candidates came from each tool, and which stage changed the rank.

Recent source notes:

- Sourcegraph Cody documents keyword search as an out-of-the-box code context source and Sourcegraph Code Search advertises literal, keyword, regex search plus SCIP-powered code navigation.
- Cursor documents codebase indexing as embedding-based indexing with ignore-file controls and incremental indexing.
- `Reliable Graph-RAG for Codebases: AST-Derived Graphs vs LLM-Extracted Knowledge Graphs` argues that vector-only RAG can fail on multi-hop architectural questions and compares deterministic AST-derived graph retrieval against LLM-generated knowledge graphs.
- `cAST: Enhancing Code Retrieval-Augmented Generation with Structural Chunking via Abstract Syntax Tree` reports AST-structured chunking gains on RepoEval retrieval and SWE-bench generation.

## Next Hypotheses

| Hypothesis | Implementation | Expected win |
| --- | --- | --- |
| `eval_file_level_metrics` | Done in this slice: file-level precision@R, nDCG@10, MAP, hit@1, hit@3. | Reveals real ranking quality and avoids optimizing misleading precision@10. |
| `hybrid_bm25_rrf` | Replace term coverage and min-max weighted fusion with BM25 postings and RRF. | Better exact-term and identifier queries; less weight tuning. |
| `tool_router_v1` | Add deterministic query-shape router that emits vector/BM25/symbol/path/graph weights. | Better per-case routing without LLM tokens. |
| `hybrid_rerank_once` | One bounded Gemini/OpenAI/local rerank call over top-20 candidates. | Better hit@1/MRR on ambiguous cases. |
| `bounded_verify_reads` | Read top 3-5 ranges only after rerank. | Cleaner final answer context and citations. |

## What To Measure Next

- Per-case source contribution: which stage produced the first relevant file.
- Per-query route: exact/path/symbol/workflow/semantic.
- File-level deltas against vector control.
- Rank movement after each stage: vector rank, BM25 rank, graph rank, fused rank, reranked rank.
- Token and latency cost per stage.
