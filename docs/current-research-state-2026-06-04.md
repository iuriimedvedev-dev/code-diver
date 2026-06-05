# Current Research State - 2026-06-04

Updated: 2026-06-05. The 2026-06-04 Qwen-only rows below remain valid historical H5 rows, but the latest sequential embedding-axis comparison found a stronger file-candidate generator with EmbeddingGemma-300M.

## SOTA Status

We should **not** claim SOTA on the official CodeSearchNet/MTEB benchmark.

What we have is a strong result on our reproducible **local positive-slice** derived from `mteb/CodeSearchNetRetrieval` Python:

- 1000 queries.
- 1000 synthetic corpus files materialized from selected positive qrels.
- Code Diver file-level metrics over generated file paths.
- Not the full official corpus.
- Not the official MTEB scorer.

That makes the result useful for comparing our own hypotheses, but not enough for a public SOTA claim.

## Current Best Results

The first three rows use local Qwen3-Embedding-0.6B file-metadata embeddings and were the 2026-06-04 quality baseline. The final row is the fresh 2026-06-05 embedding-axis result on the same 1000-case positive slice, without LLM reranking.

| Setup | Embedding | Ranker | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | Precision@R | nDCG@10 | Mean ms/query | Position |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pure H3 | Qwen3-Embedding-0.6B | none | 1000 | 0.823 | 0.919 | 0.944 | 0.961 | 0.961 | 0.177 | 0.823 | 0.900 | 555 | old fastest / no API |
| H5 | Qwen3-Embedding-0.6B | Gemini 3.1 Flash Lite | 1000 | 0.904 | 0.965 | 0.977 | 0.982 | 0.982 | 0.182 | 0.904 | 0.948 | 3020 | old best quality |
| H5 compact | Qwen3-Embedding-0.6B | local Qwen3.5 4B | 1000 | 0.842 | 0.936 | 0.953 | 0.967 | 0.967 | 0.176 | 0.842 | 0.913 | 7708 | no-API LLM fallback |
| H5 file metadata | EmbeddingGemma-300M | none | 1000 | 0.848 | 0.947 | 0.964 | 0.975 | 0.975 | 0.173 | 0.848 | 0.918 | 787 | current best no-rerank candidate generator |

The project goal `Hit@10 >= 0.95` is met on the local positive-slice by all three quality profiles.

## Current Winners

| Category | Winner | Why |
| --- | --- | --- |
| Best quality | H5 + Gemini 3.1 Flash Lite | Best Hit@1, Hit@3, Hit@5, Hit@10, nDCG, MAP, and MRR. |
| Fastest | Pure H3 + Qwen embeddings | 555ms/query, no LLM call, still Hit@10 0.961 in the old Qwen baseline. |
| Cheapest external spend | Pure H3 + Qwen embeddings | Local embeddings after index is built; no ranking API. |
| Default local quality profile | H6.1 + EmbeddingGemma-300M | No API dependency during retrieval, Hit@10 0.975 on the 1000 slice, and best held-out candidate validation so far. |
| Best historical API-rerank quality | H5 + Gemini 3.1 Flash Lite | Adds about 2.47s/query and API tokens, but improved old Qwen Hit@1 from 0.823 to 0.904. |
| No-API LLM mode | H5 compact + local Qwen3.5 4B | Valid and above target, but too slow for default interactive use. |
| Best no-rerank candidate generator | H5 file metadata + EmbeddingGemma-300M | Fresh sequential 1000-case run: Hit@3 0.947, Hit@5 0.964, Recall@10 0.975, but mean latency 787ms. |

## What We Learned

1. Real embeddings are mandatory. Hash embeddings are now treated only as a reproducibility harness and proof that semantic embeddings matter.
2. File-first indexing works. We should return ranked files, while summaries/manifests/symbols/chunks remain internal retrieval evidence.
3. H3 is the right candidate generator. It is fast, deterministic, compact, and already exceeds Hit@10 0.95 on the local slice.
4. LLM ranking is the right quality layer. It improves top ordering when candidate recall is already high.
5. Open-ended agentic search is not the default. It is useful as a hard-case escalation path, but too expensive and unstable as the normal search path.
6. Local generative reranking is not free. Qwen3.5 4B avoids API spend, but costs local GPU time and is slower than Gemini Flash Lite.
7. Prompt size is a first-order performance factor. Compact candidate prompts improved local Qwen latency, but not enough to beat Gemini Lite.
8. The benchmark adapter matters. Our positive-slice is good for internal comparison, but official SOTA requires full-corpus or large-negative evaluation.

## Invalidated Runs And Fixes

Two failed/aborted eval attempts produced useful engineering fixes:

- Vertex/Gemini returned transient `499 CANCELLED` during rerank. We added bounded retry and trace fields for rerank attempts.
- One long CodeSearchNet query exceeded the local Qwen embedding server context. We now bound prefixed query/document payloads in OpenAI/OpenAI-compatible embedding providers.

## Next Honest Benchmarks

1. Add a large-negative CodeSearchNet profile: 1000 queries plus 20k/50k corpus items, including BM25 hard negatives.
2. Run full official MTEB/CodeSearchNet protocol or export results through an official-compatible scorer.
3. Compare Qwen3-Embedding-4B, EmbeddingGemma-300m, Gemini Embedding, and Voyage Code with the same H3/H5 stack.
4. Add a true cross-encoder reranker baseline, preferably Qwen3-Reranker through a real rerank endpoint.
5. Add query embedding cache/batching to reduce local embedding overhead in evals.

## Bottom Line

We are **not official SOTA** yet.

We do have a strong, reproducible local positive-slice result and a clear current direction:

```text
EmbeddingGemma file-metadata embeddings -> calibrated H6.1 hybrid file candidates -> optional agent/LLM rerank experiments.
```
