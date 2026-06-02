# IntelliJ File-Locator Sweep

Date: 2026-06-02

## Purpose

Test whether a compact file-level index can be the hot first-stage locator for a very large repository.

The target architecture is:

1. build a small persistent local embedding index over files;
2. retrieve 20-50 likely files;
3. use fast local tools (`rg`, read, path/symbol lookup) or a temporary candidate-file index for exact evidence;
4. use an API LLM only for planning, reranking, and final answer synthesis.

This sweep intentionally keeps the persistent index small. The question is not "can we store all code in Qdrant?", but "can we route the searcher to the right files cheaply enough?"

## Dataset

- Repository: `../intellij-community`
- Evaluation cases: 1,000
- Expected answers: current dataset is mostly single-file ground truth
- Important consequence: `precision@10` is naturally low because returning 10 files for a single expected file gives a maximum useful precision of `0.1`. For this dataset, `Hit@k`, `file_recall@k`, `MRR@10`, and `NDCG@10` are more informative.

## Index

File-locator index:

- one `file_summary` item per file;
- no line chunks;
- no structural chunks;
- no symbol chunks;
- no method bodies;
- payload contains path, extension, imports, top symbols, and short file head.

Measured index composition:

| Metric | Value |
| --- | ---: |
| Files / vectors | 74,906 |
| Payload text | 172.95 MB |
| Raw vector estimate, Gemini 768 dims | 230.11 MB |
| Observed Qdrant storage, Gemini API control | 378 MB |
| Graph JSON | 247.86 MB |
| Persistent locator footprint | about 626 MB before runtime overhead |

Local Qwen index storage:

| Metric | Value |
| --- | ---: |
| Raw vector estimate, Qwen 1024 dims | 306.81 MB |
| Observed Qdrant storage, local Qwen | 450 MB |
| Graph JSON | 247.86 MB |
| Persistent locator footprint | about 698 MB before runtime overhead |
| Index build time | about 26.2 min |

## Completed Runs

Gemini API embeddings are a control run, not the target production embedding path. The target remains local embeddings. The control run is still useful because it proves the compact indexing strategy can reach strong file recall.

| Run | Embedder | Search profile | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | NDCG@10 | Mean latency | p95 latency |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| API control baseline | `gemini-embedding-001`, 768d | weighted hybrid | 0.729 | 0.837 | 0.862 | 0.898 | 0.789 | 0.815 | 2.55 s | 3.27 s |
| API control RRF | `gemini-embedding-001`, 768d | RRF | 0.691 | 0.825 | 0.847 | 0.900 | 0.764 | 0.797 | 2.57 s | 3.24 s |
| API control lexical-heavy | `gemini-embedding-001`, 768d | lexical-heavy hybrid | 0.744 | 0.848 | 0.872 | 0.906 | 0.801 | 0.826 | 2.82 s | 3.70 s |
| Local Qwen baseline | `qwen3-embedding:0.6b`, 1024d | weighted hybrid | 0.628 | 0.799 | 0.841 | 0.890 | 0.721 | 0.763 | 2.54 s | 3.33 s |

The local Qwen run used the same file-locator index shape and the same baseline weighted hybrid profile as the Gemini baseline.

## Performance Notes

The local Qwen indexing trace:

- `index_items_prepared`: 2026-06-02 15:05:13 UTC;
- `index_vectors_saved`: 2026-06-02 15:31:23 UTC;
- prepared items: 74,906;
- embedding workers: 4;
- embedding batch size: 64.

The evaluation phase took about 10.6 minutes for 1,000 cases with 4 workers. A short macOS process sample during eval showed heavy Python GIL contention plus socket/zlib traffic, consistent with Python-side HTTP/Qdrant work during hybrid search. This is a search execution optimization target: connection reuse, fewer per-query round trips, batched query embedding where possible, cached lexical structures, and streaming progress traces.

## Early Conclusions

1. **File-level locator is viable.** On IntelliJ scale, a sub-1GB persistent locator can reach `0.898-0.906` Hit@10 on 1k cases.
2. **Search profile matters on the same index.** Lexical-heavy hybrid improved Hit@1 from `0.729` to `0.744` without increasing index size.
3. **RRF is not automatically better.** It preserved Hit@10 but lost Hit@1, which is exactly the metric the user feels as "found or not found first."
4. **Current local Qwen is a candidate generator, not a final ranker.** It loses `0.101-0.116` absolute Hit@1 versus Gemini control, but only `0.008-0.016` absolute Hit@10. That means it often finds the right file but ranks it too low.
5. **The next quality lever is reranking.** If the correct file is already in top 10 around 89-91% of the time, the system needs better ranking and verification over candidate files.
6. **The persistent index should stay compact.** Adding every code chunk permanently would increase storage and candidate noise. Deep code search should be query-time and scoped to candidate files.

## Next Experiments

1. Run the local Qwen index with lexical-heavy and RRF profiles to test whether the Gemini search-profile finding transfers.
2. Run the same index with a candidate-file verification strategy:
   - retrieve top 20-50 files;
   - issue targeted `rg`/read calls;
   - rerank with API LLM.
3. Compare against an ephemeral candidate-file index:
   - retrieve top 20-50 files;
   - build temporary chunks only for those files;
   - vector search locally;
   - rerank with API LLM.
4. Add multi-answer metrics for queries where several files are correct:
   - `precision@k`;
   - `recall@k`;
   - `file_f1@k`;
   - answer-set coverage.
5. Test stronger local embedders:
   - Qwen3-Embedding-4B;
   - bge-m3;
   - jina/code-specialized embedding candidates;
   - 4-bit vs 8-bit/16-bit where the runtime supports it.
