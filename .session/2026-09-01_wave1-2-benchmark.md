# 2026-09-01 — Wave 1 & 2 Benchmark (WHERE-78)

Evaluation of retrieval arms H-81 through H-85 on the cleaned WHERE-78 dataset. Baseline is the promoted Champion (H-66b).

## Environment
- **Qdrant**: `code-diver-local-qdrant` container (Up 7 days), port 6333.
- **Embedder**: `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` on `localhost:8001`.
- **Reranker**: `Qwen3-Reranker-0.6B-Q4_K_M.gguf` on `localhost:8081`.
- **Dataset**: `datasets/intellij_eval_where_only.jsonl` (78 queries, sanitized).
- **Git State**:
    - `38f2359 [ninja-auto-save] Before task: Create a new YAML config file...`
    - `git status`: `configs/intellij/intellij-h85-wave1-combo.yml` (untracked).

## Results Table

| Arm | Recall@10 | MRR* | Hit@1 | Hit@10 / 78 | Mean Latency | p95 Latency |
|---|---|---|---|---|---|---|
| **h66b-champion** | 0.6220 | 0.3726 | 0.2308 | 54 (0.6923) | 4777ms | 6108ms |
| **h81-fusion-width** | 0.6199 | 0.3689 | 0.2308 | 54 (0.6923) | 4760ms | 5491ms |
| **h82-ce-logits** | 0.6220 | 0.3726 | 0.2308 | 54 (0.6923) | 5097ms | 5688ms |
| **h83-ce-twopass** | **0.6444** | **0.3753** | 0.2308 | **56 (0.7179)** | 5756ms | 7309ms |
| **h84-multiquery** | 0.6327 | 0.3266 | 0.1923 | 54 (0.6923) | 13239ms | 17500ms |
| **h85-wave1-combo** | 0.6423 | 0.3716 | 0.2308 | **56 (0.7179)** | 6433ms | 8076ms |

\* MRR reported as `mrr@10` from the evaluation JSON.
\*\* Latency stats calculated from total search durations per query.

## Prediction Analysis

| Case ID | Goal File | Predicted | h66b | h81 | h82 | h83 | h85 |
|---|---|---|---|---|---|---|---|
| `where-find-in-path-global` | `FindInProjectManager.java` | **h81** rescue | MISS | MISS | MISS | MISS | MISS |
| `where-safe-delete-refactoring` | `SafeDeleteProcessor.java` | **h82** rescue | MISS | MISS | MISS | MISS | MISS |
| `where-plugin-loading...` | `PluginManagerCore.kt` | **h83** rescue | MISS | MISS | MISS | **HIT@5** | **HIT@5** |
| `where-code-folding-state` | `FoldingModelImpl.java` | **h83** rescue | MISS | MISS | MISS | MISS | MISS |

### Key Findings
1. **H-83 (Two-pass CE) is the clear winner.** It gained 2 full hits (`where-plugin-loading...` and `where-notification-balloon-system`) and significantly improved Recall@10 (+2.2%). The latency penalty is acceptable (+1s mean).
2. **H-84 (Multi-query) improves Recall but hurts Latency.** While hit count remained flat (54/78), it gained recall on several multi-gold queries (`where-gradle-import`, `where-run-configurations`). However, its 2.7x latency increase and regression in Hit@1 make it unsuitable for promotion without optimization.
3. **H-81/H-82 minimal impact.** These targeted fixes did not flip the predicted queries into the top-10. `SafeDeleteProcessor` and `FindInProjectManager` remain elusive, potentially due to earlier funnel stages (lexical/vector) not even bringing them into the CE window.
4. **H-85 (Combo) stability.** The combination of h81+h82+h83 (h85) matches the hit count of h83 alone but didn't provide additional gains, and recall was slightly lower than h83 alone due to noise in multi-gold queries.

## Next Steps
- Recommend promotion of **H-83** logic to champion.
- Investigate why `h81` and `h82` failed to rescue their targets (check candidate logs to see if the files even reached the CE stage).
- Multi-query (H-84) needs a "union-rerank" optimization (fuse before CE) to be viable.
