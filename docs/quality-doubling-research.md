# Quality Doubling Research

Date: 2026-05-31

Goal: find a realistic path to roughly double code-search quality without increasing agent token spend or making search slow.

## Current Baseline

Primary dataset: `datasets/protogen_eval_100.jsonl`, 100 informal code-search cases over `../protogen`.

Current best local retrieval:

| Strategy | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Mean/query | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.89 | 0.723 | 0.405 | 0.855 | 29ms | 0 |
| `hybrid_candidates_no_llm` | 0.90 | 0.734 | 0.448 | 0.865 | 78ms | 0 |
| `hybrid_candidates_graph_boost` | 0.90 | 0.734 | 0.469 | 0.865 | 80ms | 0 |

## Precision Diagnosis

The current `precision@10` number is low partly because it is the wrong metric granularity.

The dataset usually expects one or two files. Evaluation counts relevant chunks/items in a fixed top-10 list. That means a perfect user-facing answer can still have mediocre `precision@10` if the relevant answer is one file and the remaining slots are necessarily unrelated. Claude measured the dataset shape as about 1.63 expected files per case: 61 cases expect 2 files, 38 expect 1, and 1 expects 3.

Implication: doubling raw `precision@10` from `0.469` to `0.938` is not a realistic or even desirable target. It would mostly reward filling top-10 with repeated chunks from the same expected file, hurting diversity and context usefulness.

Better targets:

| Metric | Current | Realistic target | Meaning |
| --- | ---: | ---: | --- |
| Miss rate | 0.10 | 0.05 | True 2x reduction in misses. |
| MRR gap to 1.0 | 0.266 | 0.133 | Move `mrr@10` from 0.734 to about 0.867. |
| Recall gap to 1.0 | 0.135 | 0.07 | Move `recall@10` toward 0.93. |
| File-level precision@R | Not measured | Add metric first | Measures whether returned files are clean, not whether top-10 slots are filled. |
| nDCG@10 / MAP | Not measured | Add metric first | Measures graded rank quality and can improve substantially. |

## External Research Takeaways

Recent code-search work backs the same architecture direction:

- CoREB 2026 argues code search should be evaluated as a full retrieval + reranking pipeline, not only first-stage retrieval. It also reports that code-specialized embeddings dominate general encoders for code-to-code retrieval by about 2x, while short developer-style keyword queries remain hard for every model.
- Repository-level Code Search with Neural Retrieval Methods combines BM25 retrieval with neural CodeBERT reranking and reports improvements up to 80% in MAP, MRR, and P@1 over BM25 on a seven-repository dataset.
- AllianceCoder's empirical study says potential API information and in-context code help repository-level generation, while retrieved similar snippets can add noise and degrade results by up to 15%. For us, this means "more similar chunks" is not the goal; typed APIs/symbols/entrypoints are more valuable.
- Code Graph Model and RANGER both point toward agentless or structured graph RAG: repository graphs, typed structural dependencies, and query-specific graph traversal.
- Clue-RAG reports large gains from multi-partite graph indexes and query-driven constrained traversal, with lower indexing costs than LLM-heavy graph extraction.

Sources:

- `https://arxiv.org/abs/2605.04615`
- `https://arxiv.org/abs/2502.07067`
- `https://arxiv.org/abs/2503.20589`
- `https://arxiv.org/abs/2505.16901`
- `https://arxiv.org/abs/2509.25257`
- `https://arxiv.org/abs/2507.08445`

## Claude Opus Brainstorm Audit

Command: read-only Claude Code CLI with `claude-opus-4-8`.

Output artifact: `.code-diver/claude-opus-quality-brainstorm.json`.

Run metadata:

| Field | Value |
| --- | --- |
| Status | success |
| Duration | 197.1s |
| Turns | 28 |
| Cost | $3.6095495 |
| Mode | read-only, `Edit`/`Write`/`MultiEdit` disallowed |

Claude's highest-impact levers:

1. File-level aggregation and honest metrics: nDCG@10, precision@R, MAP, file-dedup ranking.
2. Code-specialized embeddings and asymmetric query/document encoding.
3. Real BM25 plus Reciprocal Rank Fusion instead of linear min-max weighted fusion.
4. One-shot listwise LLM reranker over top-20 fused candidates.
5. Multi-granularity indexing: symbols plus file summaries, gated by file-level dedup.
6. Deterministic query expansion and intent routing.
7. Query-aware graph profiles with bounded edge rebuild.
8. Native Qdrant hybrid search: payload fields, indexes, sparse vectors, and server-side fusion where possible.
9. Robust rank-based score normalization.
10. Task-type tags and per-slice metrics.

## Proposed Quality Plan

The realistic path to "2x quality" is not one huge agent loop. It is a staged retrieval system:

1. Measure correctly at file level.
2. Improve first-stage retrieval with better embeddings and BM25/RRF.
3. Add typed repository items and summaries.
4. Add one bounded rerank call only after deterministic candidate generation.
5. Use graph traversal only when query intent needs it.

Recommended next commits:

| Commit | Hypothesis | Expected benefit |
| --- | --- | --- |
| 1 | `eval_file_level_metrics` | Stop optimizing misleading `precision@10`; expose file-level precision@R, nDCG@10, MAP, hit@1, hit@3. |
| 2 | `hybrid_bm25_rrf` | Replace term coverage and min-max fusion with BM25 and RRF. |
| 3 | `code_embedding_profiles` | Make embedding model + query/document instruction prefixes hypothesis-configurable. |
| 4 | `hybrid_rerank_once` | One Gemini/OpenAI/local rerank call over top-20 candidates with strict token budget. |
| 5 | `symbol_file_summary_index` | Add file summaries and stronger symbol/file aggregation without repeating chunks in top-k. |

## Expected Metric Movement

Near-term realistic targets:

| Metric | Current best | Target after commits 1-5 |
| --- | ---: | ---: |
| `hit@10` | 0.90 | 0.94-0.96 |
| `mrr@10` | 0.734 | 0.82-0.87 |
| `recall@10` | 0.865 | 0.91-0.94 |
| `precision@10` | 0.469 | 0.50-0.60 if dedup is handled carefully |
| `file_precision@R` | not measured | 0.75+ target after adding metric |
| `nDCG@10` | not measured | primary rank-quality metric after adding metric |

## Risks

- Chasing raw `precision@10` can make the result worse by returning redundant chunks from one file.
- Reranking can improve MRR while adding token cost; it must be one-shot and bounded.
- Graph edges can explode indexing time; call/reference edges need hard budgets or incremental construction.
- Embedding comparisons are expensive because every model needs a fresh index.
- Without task-type slices, improvements can hide regressions on auth/config/CLI/test queries.
