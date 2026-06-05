# Code Search Ranking Research - 2026-06-01

## Local Baseline

Current `configs/protogen-legacy/protogen-ollama-qdrant.yml` uses local embeddings for the main full-repo benchmark:

- Embedding provider: `openai_compatible`
- Embedding model: `mxbai-embed-large`
- Endpoint: local Ollama OpenAI-compatible embeddings API
- Vector DB: local Qdrant collection `protogen_ollama_embeddings`
- LLM reranking provider: Vertex, configurable per experiment hypothesis

So the main index is local-vectorized. Gemini is used as a bounded listwise reranker, not as the embedding model, in the reported hybrid rerank runs.

## What Strong Ranking Systems Do

Modern code RAG ranking is not "one vector search and done". The common high-quality shape is:

1. Generate a broad candidate pool with dense retrieval, lexical/BM25, symbol/path matching, and structural graph expansion.
2. Normalize candidates into structured records with stable IDs, file paths, line ranges, symbol kind, base scores, snippets, and graph features.
3. Rerank top-K with a stronger interaction model:
   - cross-encoder reranker for fast pairwise query-document scoring,
   - late-interaction model such as ColBERT for token-level matching,
   - LLM listwise reranker when intent is informal and multi-file.
4. Use route-specific ranking behavior:
   - exact path/symbol queries need lexical and path precision,
   - semantic "where is auth handled" queries need LLM/cross-encoder judgment,
   - workflow queries need graph candidates plus final rerank.
5. Evaluate with hard negatives and per-bucket metrics, not just aggregate Hit@10.

Recent public work points in the same direction. CoREB explicitly frames production code search as retrieval plus reranking, not first-stage retrieval only. SemEval-style 2026 RAG systems use query rewriting, hybrid retrieval, and cross-encoder reranking as a three-stage pipeline. ColBERT remains relevant because late interaction gives richer matching than single-vector embeddings while staying cheaper than full cross-encoder scoring over the whole corpus. Jina's reranker line also positions code-aware reranking as a distinct stage for agentic/code retrieval.

## What We Were Missing

The main missing piece was not "more graph weight". Our deterministic hybrid runs already show candidate recall is decent while rank-one precision is weak.

Missing or weak pieces:

- A cheap learned reranker. We have LLM listwise rerank, but no local/API cross-encoder or late-interaction reranker yet.
- Per-hypothesis generation config. Before this change, changing the rerank model required a temp config.
- Correct model cost for `gemini-3.1-flash-lite`.
- Hard-negative mining. Current eval can show direction, but it is still too small to tune subtle rankers confidently.
- Rank movement logging by stage. We log LLM selected indices, but we do not yet persist vector rank, lexical rank, graph rank, fused rank, and reranked rank as one structured row per candidate.
- Parallel reranking. Current 100-case eval sends one generation call per query sequentially.
- Reranker distillation. If LLM reranking keeps winning, we should use its decisions to train or tune a cheaper local reranker.

## Gemini 3.1 Flash-Lite Rerank Results

Google describes Gemini 3.1 Flash-Lite as a low-cost, low-latency Gemini 3-series model available through Gemini API and Vertex AI, with thinking controls. We tested it as a bounded listwise reranker, not as an embedding model.

Dataset: `datasets/protogen_eval_100.jsonl`

Index: local `mxbai-embed-large` + local Qdrant

| Run | Model | Mode | Candidates | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | MAP@10 | Mean search ms | Trace cost |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1fcf4bb5ea1c4735abbc8f8f5b8e179a` | `gemini-3.1-flash-lite` | compact | 20 | 0.780 | 0.880 | 0.910 | 0.833 | 0.764 | 0.714 | 2588 | $0.135 |
| `da2f58c4cc4245759736144ae6e29fff` | `gemini-3.1-flash-lite` | file_first | 40 | 0.760 | 0.890 | 0.930 | 0.829 | 0.767 | 0.710 | 3072 | $0.325 |
| `427eff134985458fa5bd38f4bc3433d1` | `gemini-3.5-flash` | file_first | 40 | 0.730 | 0.880 | 0.930 | 0.809 | 0.752 | 0.694 | ~4070 model ms | $2.079 |
| `427eff134985458fa5bd38f4bc3433d1` | `gemini-3.5-flash` | compact | 20 | 0.700 | 0.860 | 0.910 | 0.788 | 0.734 | 0.675 | ~2380 model ms | $0.850 |
| `ce1e2ae243214f01a6902dfae08be2b3` | none | routed vector guard | n/a | 0.640 | 0.810 | 0.900 | 0.734 | 0.692 | 0.624 | 133 | $0 |

## Interpretation

Flash-Lite is not "too dumb" for ranking here. On this dataset it is the best rank-one model we have tested:

- `compact` Flash-Lite is the best interactive profile: highest Hit@1, highest MRR, low token cost.
- `file_first` Flash-Lite is the best recall profile: higher Hit@10 and workflow recall, but lower Hit@1 and higher cost.
- The LLM should absolutely own final ranking for ambiguous informal queries, but only after deterministic candidate generation.
- Deterministic hybrid should stay as candidate generation and latency fallback, not as the quality ceiling.

The surprising part is that `gemini-3.1-flash-lite` beat the previous `gemini-3.5-flash` reranker on this exact task. That may be because compact ranking is mostly instruction following plus local evidence comparison, not deep code reasoning. Smaller/faster models can do that well when the candidate records are structured.

## Recommended Ranking Architecture

Default interactive path:

1. Hybrid candidate generation: vector + BM25 + path/symbol + graph expansion.
2. Deduplicate by file/symbol while preserving strongest evidence records.
3. Send top 20 structured candidates to `gemini-3.1-flash-lite` compact listwise rerank.
4. Return reranked top 10.
5. Optionally read only the top 1-3 excerpts for final answer/citation.

High-recall path:

1. Generate top 40 candidates.
2. Use `gemini-3.1-flash-lite` file-first rerank.
3. Use this for workflow questions or batch analysis where Hit@10 matters more than first answer latency.

Next experiments:

1. Add a fast cross-encoder or late-interaction reranker and compare it against Flash-Lite compact.
2. Add stage-level rank movement metrics per candidate.
3. Add hard-negative mining from the cases where Flash-Lite still misses.
4. Try query-route gating: deterministic only for exact symbol/path lookups, Flash-Lite compact for semantic/workflow queries.
5. Distill Flash-Lite choices into a local reranker if API cost or latency becomes the blocker.

## References

- Google Gemini 3.1 Flash-Lite announcement and pricing: https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-flash-lite/
- Vertex AI pricing and billing rules: https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing
- CoREB code retrieval and reranking benchmark: https://arxiv.org/abs/2605.04615
- SemEval 2026 three-stage retrieval with cross-encoder reranking: https://arxiv.org/abs/2605.12028
- ColBERT late interaction retrieval: https://arxiv.org/abs/2004.12832
- Jina reranker documentation: https://jina.ai/en-US/reranker/
