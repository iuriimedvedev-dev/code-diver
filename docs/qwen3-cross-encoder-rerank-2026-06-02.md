# Qwen3 Cross-Encoder Rerank - 2026-06-02

## Setup

This run tested a dedicated local reranker instead of using a generative LLM as a JSON-ranking model.

| Component | Value |
| --- | --- |
| Dataset | `datasets/protogen_eval_100.jsonl` |
| Candidate index | Qwen3 Embedding 0.6B 4-bit in local Qdrant |
| Candidate strategy | `hybrid_candidates_symbol_first` |
| Reranker | `Qwen3-Reranker-0.6B` |
| Runtime | llama.cpp `/v1/rerank` |
| Model file | `Qwen3-Reranker-0.6B-Q4_K_M.gguf` |
| Server flags | `--reranking --pooling rank` |
| Candidate limit | 40 |
| Max document chars | 900 |
| Trace | `.code-diver/traces/protogen-qwen-cross-encoder-rerank.jsonl` |
| Summary artifact | `.code-diver/reports/protogen-qwen-cross-encoder-rerank-summary.json` |

## Result

| Strategy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | MAP@10 | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hybrid baseline | 0.48 | 0.70 | 0.78 | 0.85 | 0.604 | 0.591 | 0.516 | 206ms |
| Hybrid + Qwen3 cross-encoder | 0.59 | 0.73 | 0.77 | 0.88 | 0.673 | 0.656 | 0.589 | 2182ms |

## Interpretation

The cross-encoder reranker improved first-rank precision substantially:

| Metric | Delta |
| --- | ---: |
| Hit@1 | +0.11 |
| Hit@3 | +0.03 |
| Hit@10 | +0.03 |
| MRR@10 | +0.069 |
| nDCG@10 | +0.065 |
| MAP@10 | +0.073 |

This confirms the audit finding: a dedicated reranker is a better ranking primitive than a small generative model forced to emit JSON. It also confirms that reranking is not free; Qwen3-Reranker 0.6B Q4 through llama.cpp is around 10x slower than deterministic hybrid search on this setup.

## Next Tests

1. Try a larger or less aggressively quantized Qwen3 reranker if it fits locally.
2. Reduce `candidate_limit` from 40 to 20 and 30 to measure quality/latency tradeoff.
3. Add a confidence gate: use cross-encoder only when deterministic scores are close or the route is hard.
4. Run the same reranker over the IntelliJ 1k quality index after the richer index is built.
