# T0 Quality Improvement Run - 2026-06-01

## Scope

This run tests the cheap ranking changes from `.plans/2026-06-01_quality-improvement-proposals.md` against the existing `protogen` Qdrant index. No reindex was performed, so the embedding-prefix implementation is covered by unit tests only in this pass.

## Implemented Changes

- Embedding providers now expose configurable `document_prefix` and `query_prefix` fields for OpenAI-compatible embeddings.
- Hybrid retrieval now supports `preserve_vector_top` with `vector_top_score_margin`.
- `configs/protogen-legacy/protogen-ollama-qdrant.yml` now contains guarded routed/GraphRAG hypotheses.
- Unit coverage was added for config loading, provider prefix payloads, and vector-top guard behavior.

## Deterministic Eval Results

Run `3272260ea47840b695c2800da454e7ad`, dataset `datasets/protogen_eval_100.jsonl`, limit `10`.

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | MAP@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.640 | 0.780 | 0.880 | 0.720 | 0.679 | 0.612 | 35.6 |
| `hybrid_candidates_no_llm` | 0.630 | 0.780 | 0.890 | 0.721 | 0.683 | 0.616 | 128.5 |
| `hybrid_candidates_routed` | 0.630 | 0.790 | 0.900 | 0.722 | 0.687 | 0.618 | 133.7 |
| `hybrid_candidates_modern_graphrag` | 0.620 | 0.810 | 0.900 | 0.718 | 0.682 | 0.613 | 136.7 |
| `hybrid_candidates_routed_vector_guard` | 0.630 | 0.790 | 0.900 | 0.722 | 0.687 | 0.618 | 133.9 |
| `hybrid_candidates_modern_graphrag_vector_guard` | 0.620 | 0.810 | 0.900 | 0.718 | 0.682 | 0.613 | 135.7 |

Guard ablation run `ce1e2ae243214f01a6902dfae08be2b3`.

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | MAP@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_candidates_routed_vector_guard_always` | 0.640 | 0.810 | 0.900 | 0.734 | 0.692 | 0.624 | 133.1 |

## Interpretation

Route-conditional fusion improves recall-oriented metrics, but still loses Hit@1 against plain vector. The always-on vector guard recovers vector Hit@1 while preserving routed Hit@10, and improves MRR/nDCG/MAP. The margin-based guard at `0.03` had no measurable effect, which means confident vector margins are rare in the cases where hybrid fusion changes the first result.

Modern GraphRAG currently helps Hit@3 and Hit@10, especially workflow queries, but hurts Hit@1 and MRR. It is useful as candidate generation, not as a final ranker without a better rerank stage.

The maximum deterministic score observed in this pass is `hybrid_candidates_routed_vector_guard_always`: Hit@1 `0.640`, Hit@10 `0.900`, nDCG@10 `0.692`. The best quality run overall remains the bounded LLM rerank from run `427eff134985458fa5bd38f4bc3433d1`: Hit@1 `0.730`, Hit@10 `0.930`, nDCG@10 `0.752`, mean model latency about `4.07s`.

## Next Hypotheses

1. Reindex into a separate Qdrant collection with document prefixes enabled, then compare against the current query-prefixed-only baseline.
2. Use GraphRAG only for candidate expansion, then apply either vector-top guard or a fast cross-encoder reranker for final ordering.
3. Learn route-specific weights from eval logs instead of hand-tuning global weights.
4. Add hard-negative cases where vector top is wrong, so the guard can be tuned by expected risk rather than aggregate metrics only.
5. Test a code-specialized embedding model before further fusion work; current deterministic gains are too small to justify more complex handcrafted ranking.
