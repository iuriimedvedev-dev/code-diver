# IntelliJ Eval Validity Review - 2026-06-03

## Status

This is an interim review of the IntelliJ 1000-case code-search evaluation. It combines local checks and a parallel subagent audit. A Claude Code CLI audit is running separately and should be appended when it completes.

## Main Conclusion

The current H3 manifest result is directionally strong, but the headline `Hit@10=0.976` on `datasets/intellij_eval_1000.answer_sets.jsonl` is optimistic. It should be reported together with stricter rescoring:

| Scoring mode | H3 Hit@10 estimate | Interpretation |
|---|---:|---|
| Full `answer_sets` | 0.976 | Most permissive; includes curated additions and `glob:` labels. |
| No `glob:` labels | ~0.946 | Better estimate for exact-file benchmark quality. |
| Older `multi_expected` labels | ~0.938 | Stricter pre-expansion comparison point. |

The system is not bogus. It still looks strong under stricter labels. But the `0.976` number should not be used alone as a product-quality claim.

## Dataset Shape

Observed files:

| Dataset | Rows | Duplicate IDs | Duplicate Queries | Mean expected | Multi-answer rate | Max expected | Missing exact paths |
|---|---:|---:|---:|---:|---:|---:|---:|
| `datasets/intellij_eval_1000.jsonl` | 1000 | 0 | 28 | 1.00 | 0.0% | 1 | 0 |
| `datasets/intellij_eval_1000.multi_expected.jsonl` | 1000 | 0 | 28 | 1.17 | 3.8% | 10 | 0 |
| `datasets/intellij_eval_1000.answer_sets.jsonl` | 1000 | 0 | 28 | 1.28 | 7.1% | 10 | 0 |

`answer_sets` differs from `multi_expected` in 45 rows. It adds curated extra files and query-triggered `glob:` alternatives.

Case source mix in `answer_sets`:

| Prefix | Count |
|---|---:|
| `config` | 329 |
| `path` | 328 |
| `symbol` | 329 |
| `where` | 14 |

## Validity Risks

1. The dataset is mostly synthetic and path/symbol-derived.

   The generator creates many queries from file stems, parent directory names, and extracted symbol names. This is useful for locator stress testing, but it over-rewards lexical/path matching versus real human navigation queries.

2. Literal overlap is high.

   Rough local check on `answer_sets`:

   | Overlap check | Mean | P50 | P90 | Cases >= 0.5 | Cases >= 0.8 |
   |---|---:|---:|---:|---:|---:|
   | Query tokens in expected basename | 0.161 | 0.000 | 0.667 | 204 | 23 |
   | Query tokens in expected path | 0.439 | 0.333 | 1.000 | 444 | 183 |

3. Some `glob:` labels are broad.

   Broad globs can make a filename-family hit count as correct. That is sometimes useful for ambiguous queries, but it must be governed. Examples called out by the subagent include patterns like `**/*Service*.kt`, `**/*Configuration*.java`, and `**/*Dependency*.kt`, which can match hundreds of files.

4. `expected` has overloaded semantics.

   The flat list currently means both:

   - all relevant files for a workflow query;
   - alternative acceptable labels, including broad globs.

   Those are different relevance models. Metrics like recall, AP, and nDCG cannot interpret them correctly without grouped semantics.

5. Overlapping labels can distort recall/AP/nDCG.

   If one returned file matches both an exact path and a glob, or two overlapping globs, the metric code can count multiple expected labels as satisfied by one returned file.

6. H3 reports need file-level Hit@1/3/5.

   H3 is a file locator. Raw item-level `hit_rate@3/@5` can be misleading when multiple chunks from the same file occupy early ranks. I added `file_hit_rate@1/@3/@5` in commit `0c7c5f9`.

## H3 Rescoring Note

Using saved H3 diagnostics, file-deduped top files give:

| Metric from diagnostics top files | Value |
|---|---:|
| File Hit@1 | 0.871 |
| File Hit@3 | 0.960 |
| File Hit@5 | 0.972 |
| File Hit@10 | 0.976 |

The existing report's `hit_rate@3=0.903` and `hit_rate@5=0.943` are item-level, not file-level. They are still valid metrics, but they are not the right headline for "find the file".

## Required Validation Checks

Add or enforce these before using the IntelliJ benchmark as a stable research claim:

1. Dataset invariants: unique ids, non-empty expected, all exact paths exist, duplicate query groups have consistent expected semantics.
2. Glob governance: every glob must match at least one file and fewer than a configured threshold unless explicitly waived.
3. Overlap detection: flag exact/glob labels that can be satisfied by the same returned file.
4. Schema upgrade: replace flat `expected` with grouped labels, e.g. `answer_groups`, where each group is "any of these is acceptable".
5. Strict rescoring: always report `full`, `no_glob`, and `exact_only` metrics.
6. Holdout split: keep a human-authored or LLM-paraphrased set that is never used to patch answer sets.
7. Per-case persistence: final reports should keep enough raw retrieved order to recompute metrics exactly, not only aggregate metrics.

## External Benchmarks To Add

Best near-term candidates:

| Benchmark | Why it matters | Fit for code-diver | Effort |
|---|---|---|---|
| `mteb/SWEbenchCodeRetrieval` | File-path retrieval for realistic software-engineering tasks. | Strong fit for file-level locator evaluation. | Medium: needs dataset adapter and per-repo indexing. |
| `CoREB` | 2026 code retrieval/reranking benchmark with graded relevance and contamination-aware releases. | Good for reranker/model comparison. | Medium: likely needs MTEB-style adapter. |
| `CodeRAG-Bench` / RepoEval | Repository-level RAG retrieval and generation benchmark. | Good for comparing against published Recall/NDCG ranges. | Medium/high. |
| `CodeSearchNetRetrieval` / CoSQA | Classic semantic snippet/function retrieval. | Useful for embedding sanity, less representative of repo navigation. | Low/medium. |

Recommendation: start with `SWEbenchCodeRetrieval`, then CoREB for reranker quality.

## Next Experiment Direction

Do not spend the next model comparison on H2. H3 manifest is the strongest candidate generator. The next matrix should run rerankers over H3 candidates:

| Hypothesis | Candidate generator | Reranker |
|---|---|---|
| `h3_ce_qwen3_0_6b` | H3 manifest union top90 | Qwen3-Reranker-0.6B via llama.cpp `/v1/rerank` |
| `h3_ce_qwen3_4b` | H3 manifest union top90 | Qwen3-Reranker-4B via llama.cpp `/v1/rerank` |
| `h3_ce_qwen3_0_6b_gemini_lite` | H3 -> CE top20 | Gemini 3.1 Flash-Lite final listwise rerank |
| `h3_ce_qwen3_4b_gemini_35` | H3 -> CE top20 | Gemini 3.5 Flash final listwise rerank |

Promote by `file_hit_rate@5`, `file_hit_rate@10`, strict/no-glob score, latency, and cost.
