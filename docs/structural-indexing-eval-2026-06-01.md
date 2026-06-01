# Structural Multi-Index Eval - 2026-06-01

## Change

Added an additive structural indexing layer:

- Existing fixed line chunks stay in the index.
- Structural chunks are added as `structural_chunk` items.
- Symbol chunks and file summaries remain separate index items.
- Hybrid ranking can add a file-level vote when several item types point at the same file.

The implementation intentionally does not replace line chunks. A replace-only run was tested first and hurt vector rank-one quality.

## Implementation

- `ScannerConfig.structural_chunks` toggles structural chunking.
- `StructuralCodeChunker` uses Python AST top-level class/function spans and falls back to generic symbol spans for other languages.
- `CodeItemIndexKind.STRUCTURAL_CHUNK` marks structural chunks.
- `HybridSearchConfig.file_vote_weight` controls file-level consensus voting.
- `HybridCandidateScore.file_vote_score` participates in weighted and RRF fusion.
- Experiment metrics now record `scanner_structural_chunks` and `hybrid_file_vote_weight`.

## Index Size

| Index mode | Items |
| --- | ---: |
| previous line+symbol+summary baseline | ~9,230 |
| replace line chunks with structural chunks | 11,383 |
| additive line+structural+symbol+summary | 12,698 |

## Tested Runs

Dataset: `datasets/protogen_eval_100.jsonl`

Index: local Qdrant collection `protogen_ollama_embeddings`

### Deterministic

Run ID: `f46ea2e070564b7498a94658c1205fa5`

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.530 | 0.740 | 0.870 | 0.648 | 0.627 | 35 |
| `hybrid_candidates_modern_graphrag_vector_guard` | 0.610 | 0.740 | 0.890 | 0.692 | 0.659 | 187 |
| `hybrid_candidates_structural_file_vote` | 0.620 | 0.750 | 0.880 | 0.701 | 0.657 | 196 |

Retuned structural weights:

Run ID: `96895086a4124e61b7ced524c5f893fa`

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_candidates_structural_file_vote` | 0.580 | 0.800 | 0.900 | 0.697 | 0.661 | 190 |
| `hybrid_candidates_modern_graphrag_vector_guard` | 0.610 | 0.740 | 0.890 | 0.692 | 0.659 | 178 |

### Flash-Lite Rerank

Run ID: `45b2f8c853bf44f28d37957c67e0d3f9`

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_rerank_flash_lite_top20_compact` | 0.770 | 0.860 | 0.910 | 0.823 | 0.745 | 2410 | 5802 |
| `hybrid_rerank_flash_lite_structural_file_vote` | 0.730 | 0.880 | 0.920 | 0.807 | 0.730 | 2207 | 3635 |

Run ID: `8cfe58bb288144069b73ee4c239a7113`

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_rerank_flash_lite_structural_file_first` | 0.770 | 0.900 | 0.920 | 0.835 | 0.750 | 3709 | 9134 |

## Split Vector Retrieval

Follow-up change: structural candidates should not compete in the same vector top-k pool as line chunks and symbols. The hybrid factory now supports split vector retrieval by index kind.

Two budget modes exist:

- `vector_kind_limits`: absolute per-kind limits, useful for controlled ablations.
- `vector_kind_multipliers`: per-kind limits derived from the active `candidate_limit`, useful for large repositories.

The protogen structural hypotheses now use multipliers:

| Kind | Multiplier |
| --- | ---: |
| `chunk` | 0.45-0.46 |
| `symbol` | 0.30 |
| `file_summary` | 0.10-0.12 |
| `structural_chunk` | 0.12-0.15 |

This keeps the budget scalable: for an IntelliJ-sized repository, raise `candidate_limit` and the per-kind budgets grow without code changes.

Deterministic split-vector run:

Run ID: `26112a76562948deb95d0f88052b0db8`

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_candidates_structural_file_vote` | 0.590 | 0.800 | 0.910 | 0.709 | 0.672 | 561 |
| `hybrid_candidates_modern_graphrag_vector_guard` | 0.600 | 0.760 | 0.890 | 0.693 | 0.661 | 554 |

File-first split-vector rerank:

Run ID: `63aefacfb0c448d98691a4071a16db1b`

| Hypothesis | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_rerank_flash_lite_structural_file_first` | 0.760 | 0.890 | 0.920 | 0.828 | 0.747 | 3546 | 8787 |

Interpretation:

- Split retrieval removes structural chunks from rank-one dominance in deterministic structural runs.
- It improves deterministic recall and Hit@10 versus the unsplit structural profile.
- It slightly lowers rerank Hit@1 versus fixed absolute quotas, but avoids hard-coded small budgets and is safer for large repositories.
- For very large repositories, deterministic split search should be the default interactive mode; LLM file-first rerank should be reserved for hard queries or eval runs.

## Interpretation

Structural chunks are useful as a recall and workflow signal, but harmful when they compete directly as pure vector top-1 candidates.

Evidence:

- Replace-only structural indexing dropped vector Hit@1 sharply.
- Additive indexing still dropped pure vector Hit@1 from the previous 0.64 baseline to 0.53 because structural chunks enter the same vector pool.
- Hybrid file voting improved workflow Hit@3 and Hit@10, but not deterministic Hit@1.
- Flash-Lite structural file-first recovered Hit@1 to 0.77 and improved Hit@3/Hit@10 over compact rerank, but it is slower and still does not beat the previous best file-first baseline on nDCG.

## Decision

Keep the code path and hypotheses, but do not treat structural chunks as a proven production default yet.

Current best use:

- Enable structural chunks for recall-oriented hybrid/rerank experiments.
- Downweight `structural_chunk` as a final ranked item.
- Use file-first rerank when structural candidates are included.
- Use split vector retrieval by index kind when structural chunks are enabled.

Next experiments:

1. Route structural/file-vote only for workflow queries.
2. Add per-stage candidate logs: vector rank, lexical rank, graph rank, file-vote rank, rerank rank.
3. Test a local cross-encoder reranker on the structural candidate set.
4. Add language-specific tree-sitter spans for Kotlin/Java/TypeScript after the Python AST path is stable.
5. Build an IntelliJ evaluation dataset before trusting large-repo quality numbers.
