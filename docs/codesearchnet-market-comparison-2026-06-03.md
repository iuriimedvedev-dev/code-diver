# CodeSearchNet Market Comparison - 2026-06-03

This note compares our public CodeSearchNet/MTEB runner against public results for the same MTEB task.

## Scope

Benchmark: `mteb/CodeSearchNetRetrieval`, Python subset, `test`, 1000 queries / 1000 corpus items materialized by our `codesearchnet-mteb-python-1000` benchmark profile.

Important caveat: our local runner reports `Hit@k`, `Recall@k`, `Precision@k`, `MAP@10`, and `nDCG@10` from Code Diver. The public MTEB `mteb/results` table stores a single official `score` per model/subset. Use the public table as the market/SOTA reference, not as a byte-for-byte reproduction of our runner.

## Our Current Public Runner

These are reproducible no-key profiles using `hash-token-v1`, so reviewers can run them without API keys or local model servers.

| Setup | Runs | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MAP@10 | nDCG@10 | Mean ms/query | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `vector_chunks` | 3 | 0.164 | 0.300 | 0.364 | 0.476 | 0.476 | 0.0476 | 0.251 | 0.304 | 86 | Stable pipeline baseline. |
| `h2_line_symbol_hybrid` | 2 matching | 0.295 | 0.510 | 0.595 | 0.708 | 0.708 | 0.0998 | 0.425 | 0.493 | 195 | Best stable pair before drift. |
| `h2_line_symbol_hybrid` | drift run | 0.213 | 0.365 | 0.463 | 0.622 | 0.622 | 0.1042 | 0.320 | 0.391 | 205 | Reproducibility warning. |
| `h2_line_symbol_hybrid` | verify single-run | 0.275 | 0.458 | 0.553 | 0.675 | 0.675 | 0.1072 | 0.394 | 0.461 | 201 | Confirms nondeterministic ranking/ordering risk. |
| `pure_h3` | 1 | 0.320 | 0.607 | 0.681 | 0.775 | 0.775 | 0.1030 | 0.481 | 0.552 | 316 | Best completed no-key quality run. |
| `h2_summary_manifest_hybrid` | incomplete | - | - | - | - | - | - | - | - | >240s before termination | Too slow in this hash-only sweep. |

Observed artifacts:

- `vector_chunks` is deterministic across three runs.
- `h2_line_symbol_hybrid` is not deterministic enough: a deterministic no-key setup produced materially different rankings across processes.
- The likely fault class is unstable candidate tie-breaking or set/dict ordering inside hybrid ranking, not model nondeterminism.
- `pure_h3` is currently the strongest completed no-key architecture run on this public benchmark, but it still needs repeated clean runs after the determinism bug is fixed.

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

No, not on public CodeSearchNet/MTEB.

The best completed no-key Code Diver profile so far is `pure_h3` with `nDCG@10 = 0.552` and `Hit@10 = 0.775`. Public embedding models on the same MTEB task are around `0.94-0.967` official score on the Python subset.

That does not invalidate the architecture. It clarifies the gap:

1. Our public no-key benchmark uses hash embeddings, so it validates the pipeline and ranking architecture, not the quality ceiling.
2. Hybrid structural/sparse signals matter: Pure H3 improved `Hit@10` from `0.476` to `0.775` over the vector hash baseline.
3. To approach market quality, the quality profile must use a real code-aware embedding model: Qwen3-Embedding-4B, Qwen3-Embedding-8B, EmbeddingGemma, Gemini embedding, or Voyage Code.
4. Before claiming any final number, fix deterministic ordering in hybrid search and rerun Pure H3 several times.

## Recommended Next Benchmark Matrix

Priority order for quality runs:

1. Fix hybrid ranking determinism and add a regression test that identical index/config/query produces identical top-k across processes.
2. `pure_h3 + Qwen3-Embedding-4B`.
3. `pure_h3 + google/embeddinggemma-300m`.
4. `pure_h3 + Qwen3-Embedding-0.6B` as the cheap local baseline.
5. `pure_h3 + Gemini embedding` as an API ceiling.
6. `pure_h3 + Voyage Code 3` as a code-specialized API ceiling.
7. Add Qwen3-Reranker after the strong embedder baseline is established.

The honest current status: we built the benchmark and a reproducible no-key baseline path, but we have not proven SOTA-quality public CodeSearchNet performance until the real embedding profiles are run and the hybrid determinism issue is fixed.
