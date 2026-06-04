# CodeSearchNet Market Comparison - 2026-06-03

This note compares our public CodeSearchNet/MTEB runner against public results for the same MTEB task.

## Scope

Benchmark source: `mteb/CodeSearchNetRetrieval`, Python subset, `test`.

Our current runner materializes a local positive-slice: selected qrel positives become synthetic files, then Code Diver searches those files. This is useful for reproducible product benchmarking, but it is not the official full-corpus MTEB retrieval protocol.

Important caveat: our local runner reports `Hit@k`, `Recall@k`, `Precision@k`, `MAP@10`, and `nDCG@10` from Code Diver. The public MTEB `mteb/results` table stores a single official `score` per model/subset. Use the public table as the market/SOTA reference, not as a byte-for-byte reproduction of our runner.

## Our Current Quality Runner

These rows use local Qwen3-Embedding-0.6B file-metadata embeddings. H3 is the deterministic file candidate generator; H5 adds an LLM final ranker over H3 candidates.

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MAP@10 | nDCG@10 | Mean ms/query | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `pure_h3_qwen_index` | 1000 | 0.823 | 0.919 | 0.944 | 0.961 | 0.961 | 0.177 | 0.880 | 0.900 | 555 | Fast/free local quality baseline. |
| `h5_qwen_index_gemini_flash_lite_top10` | 1000 | 0.904 | 0.965 | 0.977 | 0.982 | 0.982 | 0.182 | 0.936 | 0.948 | 3,020 | Best measured quality/cost tradeoff. |
| `h5_qwen_index_qwen35_4b_compact_top10` | 1000 | 0.842 | 0.936 | 0.953 | 0.967 | 0.967 | 0.176 | 0.895 | 0.913 | 7,708 | Local no-API ranker; too slow for default use. |

## Discarded Hash Harness

These are reproducible no-key profiles using `hash-token-v1`, so reviewers can run them without API keys or local model servers.

| Setup | Runs | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MAP@10 | nDCG@10 | Mean ms/query | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `vector_chunks` | 3 | 0.164 | 0.300 | 0.364 | 0.476 | 0.476 | 0.0476 | 0.251 | 0.304 | 86 | Stable pipeline baseline. |
| `h2_line_symbol_hybrid` | 2 matching | 0.295 | 0.510 | 0.595 | 0.708 | 0.708 | 0.0998 | 0.425 | 0.493 | 195 | Best stable pair before drift. |
| `h2_line_symbol_hybrid` | drift run | 0.213 | 0.365 | 0.463 | 0.622 | 0.622 | 0.1042 | 0.320 | 0.391 | 205 | Reproducibility warning. |
| `h2_line_symbol_hybrid` | verify single-run | 0.275 | 0.458 | 0.553 | 0.675 | 0.675 | 0.1072 | 0.394 | 0.461 | 201 | Confirms nondeterministic ranking/ordering risk. |
| `pure_h3_hash` | 1 | 0.320 | 0.607 | 0.681 | 0.775 | 0.775 | 0.1030 | 0.481 | 0.552 | 316 | Reproducibility harness only. |
| `h2_summary_manifest_hybrid` | incomplete | - | - | - | - | - | - | - | - | >240s before termination | Too slow in this hash-only sweep. |

Observed artifacts:

- `vector_chunks` is deterministic across three runs.
- `h2_line_symbol_hybrid` is not deterministic enough: a deterministic no-key setup produced materially different rankings across processes.
- The likely fault class is unstable candidate tie-breaking or set/dict ordering inside hybrid ranking, not model nondeterminism.
- The hash harness is no longer used for quality conclusions. It remains useful as evidence that real semantic embeddings are required.

## Public MTEB Results Extract

Source: `mteb/results` parquet dataset, filtered locally by:

- `task_name == CodeSearchNetRetrieval`
- `subset == python`
- `split == test`

Top public Python rows extracted on 2026-06-03:

| Rank | Model | MTEB score | Trained on task |
| ---: | --- | ---: | --- |
| 1 | `Bytedance/Seed1.6-embedding-1215` | 0.97161 | yes |
| 2 | `google/text-embedding-005` | 0.96794 | no |
| 3 | `voyageai/voyage-code-3` | 0.96688 | no |
| 4 | `Qwen/Qwen3-Embedding-8B` | 0.96588 | no |
| 5 | `google/gemini-embedding-001` | 0.96495 | no |
| 6 | `ICT-TIME-and-Querit/ICT-TIME-and-Querit-embedding-v1` | 0.96214 | no |
| 7 | `google/embeddinggemma-300m` | 0.96180 | no |
| 8 | `Qwen/Qwen3-Embedding-4B` | 0.96004 | no |
| 17 | `Qwen/Qwen3-Embedding-0.6B` | 0.94325 | no |
| 33 | `openai/text-embedding-3-large` | 0.92363 | no |

Selected model takeaway:

- Qwen3-Embedding-4B is materially stronger than Qwen3-Embedding-0.6B on this public task: `0.96004` vs `0.94325`.
- Qwen3-Embedding-8B adds only `+0.00584` over 4B on Python CodeSearchNet, so 4B looks like the better local quality/cost target unless we need the absolute ceiling.
- `google/embeddinggemma-300m` is surprisingly strong here (`0.96180`) and should be added to the local embedding candidate list.
- `voyage-code-3`, `google/text-embedding-005`, and `gemini-embedding-001` define the API ceiling for this benchmark family.

## Did We Reach SOTA?

Not proven on official public CodeSearchNet/MTEB.

The best measured Code Diver local positive-slice profile so far is `h5_qwen_index_gemini_flash_lite_top10` with `Hit@10 = 0.982` and `nDCG@10 = 0.948` on 1000 local-slice cases. Public embedding models on the official full MTEB task are around `0.94-0.967` official score on the Python subset.

That does not invalidate the architecture. It clarifies the gap:

1. Real embeddings were the biggest lever: Qwen3-Embedding-0.6B changed H3 from hash-harness `Hit@10 = 0.775` to quality-slice `Hit@10 = 0.961`.
2. LLM ranking is a real ordering lever: Gemini Flash Lite improved `Hit@1` from `0.823` to `0.904` over the same Qwen H3 index.
3. To make an official SOTA claim, run the official full-corpus MTEB protocol or a larger negative-pool profile, not only the local positive slice.
4. To improve quality further, test Qwen3-Embedding-4B, EmbeddingGemma-300m, Gemini embedding, and Voyage Code against the same H3/H5 stack.

## Recommended Next Benchmark Matrix

Priority order for quality runs:

1. Finish 1000-case runs for `pure_h3_qwen_index`, `h5_qwen_index_gemini_flash_lite_top10`, and the local no-API ranker.
2. Add a larger negative-pool profile: 1000 queries plus 20k/50k corpus items and BM25 hard negatives.
3. `pure_h3/H5 + Qwen3-Embedding-4B`.
4. `pure_h3/H5 + google/embeddinggemma-300m`.
5. `pure_h3/H5 + Gemini embedding` as an API ceiling.
6. `pure_h3/H5 + Voyage Code 3` as a code-specialized API ceiling.
7. Add a specialized cross-encoder reranker after the strong embedder baseline is established.

The honest current status: the local positive-slice result is now strong, but it is not an official SOTA claim until we run a full-corpus or large-negative public profile.
