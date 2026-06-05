# Full Dataset Benchmark - 2026-06-01

Run ID: `f6126ddf8af1424682e1794ec09145d1`

Dataset: `datasets/protogen_eval_100.jsonl`

Config: `configs/protogen-legacy/protogen-ollama-qdrant.yml`

Index: local Ollama `mxbai-embed-large` embeddings, local Qdrant collection `protogen_ollama_embeddings`

Limit: `10`

## Summary

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | MAP@10 | Mean ms | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.640 | 0.780 | 0.880 | 0.720 | 0.679 | 0.612 | 36.9 | $0 |
| `hybrid_candidates_routed` | 0.630 | 0.790 | 0.900 | 0.722 | 0.687 | 0.619 | 136.7 | $0 |
| `hybrid_candidates_routed_vector_guard_always` | 0.640 | 0.810 | 0.900 | 0.734 | 0.692 | 0.624 | 135.3 | $0 |
| `hybrid_rerank_flash_lite_top20_compact` | 0.780 | 0.890 | 0.910 | 0.835 | 0.763 | 0.712 | 2193.8 | $0.135 |
| `hybrid_rerank_flash_lite_file_first` | 0.780 | 0.890 | 0.930 | 0.842 | 0.776 | 0.721 | 3321.6 | $0.325 |

## Flash-Lite Usage

Trace source: `.code-diver/traces/protogen-ollama-qdrant-indexing.jsonl`, last 200 `llm_rerank_response` events.

| Hypothesis | Calls | Input tokens | Output tokens | Total tokens | Estimated cost | Mean model ms | P95 model ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_rerank_flash_lite_top20_compact` | 100 | 469,920 | 11,514 | 497,570 | $0.135 | 2004.0 | 3729.5 |
| `hybrid_rerank_flash_lite_file_first` | 100 | 1,126,200 | 28,763 | 1,176,931 | $0.325 | 3130.5 | 8354.2 |

## Bucket Notes

`vector_qdrant` is strongest on semantic Hit@1 (`0.733`) but weak on workflow Hit@1 (`0.564`).

The deterministic routed guard improves over vector on Hit@3, Hit@10, MRR, nDCG, and MAP, but still does not improve aggregate Hit@1. It is useful as candidate generation and fallback, not as the final ranker.

`hybrid_rerank_flash_lite_top20_compact` gives the biggest rank-one jump at low cost:

- overall Hit@1: `0.780`
- path/symbol Hit@1: `0.871`
- semantic Hit@1: `0.733`
- workflow Hit@1: `0.744`

`hybrid_rerank_flash_lite_file_first` is the best full-dataset winner in this run:

- highest Hit@10: `0.930`
- highest MRR@10: `0.842`
- highest nDCG@10: `0.776`
- highest MAP@10: `0.721`
- workflow Hit@10: `0.949`

## Decision

Use `hybrid_rerank_flash_lite_top20_compact` as the default interactive profile when latency and cost matter.

Use `hybrid_rerank_flash_lite_file_first` for high-quality/batch mode when the extra second and roughly 2.4x token cost are acceptable.

The next optimization should be parallel rerank execution plus route gating:

1. exact symbol/path query -> deterministic hybrid or guarded vector,
2. semantic/workflow query -> Flash-Lite rerank,
3. batch/high recall -> Flash-Lite file-first.
