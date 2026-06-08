# H10 - Graph-First FileRAG

| Field | Value |
| --- | --- |
| ID | `H10` |
| Status | active, not default |
| Motivation | Test the user's proposal: replace the flat hybrid file ranker with a file graph ranker, while preserving the same H5/H6 file metadata that made the index strong. |
| Assumptions | File nodes with summary/manifest metadata plus graph propagation can improve file ordering, especially on multi-file repositories where imports/references/calls matter. |
| Index composition | Qwen3-Embedding-0.6B local embeddings over `file_summary` and `file_manifest`; graph artifact over the same items. CodeSearchNet graph currently has only summary-to-manifest edges after filtering false reference edges. |
| Search/ranking flow | Historical CodeSearchNet row: query -> base hybrid seeds from file metadata -> file graph propagation -> file-level candidate ranking -> Gemini 3.1 Flash Lite rerank over file summaries -> top files. Current local work replaces the API reranker with configured local Gemma/llama.cpp when rerank is enabled. |
| Model/provider matrix | Historical row: `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` embeddings and Vertex `gemini-3.1-flash-lite` rerank. Current default wiring: local Qwen/EmbeddingGemma file metadata embeddings plus local Gemma 4 26B-A4B generation/rerank experiments. |
| Dataset | Historical top table: `.code-diver/tmp/codesearchnet_python_100.jsonl`, 100 public CodeSearchNet/MTEB Python cases, one expected file per query. Current check: IntelliJ answer-set rows below. |
| Metrics | Baseline H5/H6 `hybrid_rerank`: Hit@1 `0.860`, Hit@3 `0.930`, Hit@5 `0.960`, Hit@10 `0.960`, NDCG@10 `0.9153`, MAP@10 `0.9003`, mean `1446.7 ms`. H10 after fixes: Hit@1 `0.870`, Hit@3 `0.960`, Hit@5 `0.960`, Hit@10 `0.960`, NDCG@10 `0.9229`, MAP@10 `0.9100`, mean `2002.8 ms`. |
| Cost/latency/index-size | Historical H10 was slower on the 100-case CodeSearchNet slice because it still ran Gemini rerank and added graph/catalog work. Reindex of 2,000 file-level items took about `36 s`; index artifact `44-46 MB`, graph artifact about `2 MB`. |
| Result summary | The initial H10 run failed because `file_summary`/`file_manifest` were treated as real symbols, creating 2,000 false `references` edges and a mega-hub into `python/0001...`; Hit@1 dropped to `0.710`. After filtering non-symbol metadata kinds and preferring `file_summary` as rerank evidence, H10 slightly beat baseline quality on 100 cases but remained slower. |
| Decision | Keep H10 active for multi-file repository experiments, but do not promote it over the current calibrated hybrid default yet. On single-snippet CodeSearchNet, graph has little real topology; its value should be judged on repositories with imports, references, calls, and package structure. |
| Failure modes | Bad graph edges create hub effects; file-level graph collapse can hide useful summary text if manifest is selected as the representative; graph propagation can add related-but-wrong files when topology is weak. |
| Follow-ups | Add graph edge quality metrics, gate graph propagation when graph density/topology is weak, test H10 on Protogen/IntelliJ answer-set cases, and compare graph-first with hybrid-plus-graph-signal under identical reranker/candidate limits. |
| Links | `configs/benchmarks/codesearchnet-h10-graph-file-qwen-quality-100.yml`, `.code-diver/traces/codesearchnet-h10-graph-file-qwen-quality-100.jsonl`, `src/code_diver/strategies/graph_file_retrieval_strategy.py`, `src/code_diver/graph/code_graph_builder.py` |

## IntelliJ Answer-Set Check - 2026-06-08

The first IntelliJ H10 runs exposed a wiring bug: `graph_file` and
`graph_file_rerank` were seeded by the vector-only multi-index strategy instead
of the full calibrated hybrid strategy. That made H10 look worse than H7 for the
wrong reason. The factory now builds graph-file strategies on top of the same
`HybridRetrievalStrategy` used by H7/H6.1.

All rows below use the same IntelliJ file-locator index:

- Repository: `../intellij-community`
- Dataset: `datasets/intellij_eval_1000.answer_sets.jsonl`
- Index: file summaries + file manifests
- Embeddings: local `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`
- Reranker: none
- Limit: 10

| Setup | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | File recall@10 | NDCG@10 | MAP@10 | Mean ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H7/H6.1 calibrated hybrid | 0.746 | 0.882 | 0.912 | 0.933 | 0.9141 | 0.1847 | 0.9019 | 0.8306 | 0.7975 | 84.1 | 155.2 |
| H8 hybrid with graph signal | 0.746 | 0.882 | 0.912 | 0.933 | 0.9141 | 0.1847 | 0.9019 | 0.8306 | 0.7975 | 85.6 | 162.0 |
| H10 graph-file wrapper, true graph expansion | 0.747 | 0.885 | 0.915 | 0.935 | 0.9149 | 0.1205 | 0.9044 | 0.8320 | 0.7986 | 336.9 | 447.6 |

Result: current containment-only file graph is not strong enough to replace the
calibrated hybrid file locator. H10 gives a small quality lift on IntelliJ
answer-set cases, but the latency cost is about 4x. The next useful GraphRAG
step is not more weight tuning; it is better topology: module/package ownership,
imports, extension declarations, call/reference edges, and edge-quality gates.

Gemini 3.1 Flash Lite rerank was also checked on the 100-case IntelliJ slice:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | File recall@10 | NDCG@10 | MAP@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H7/H6.1 hybrid + Gemini Lite rerank | 100 | 0.810 | 0.940 | 0.960 | 0.990 | 0.9395 | 0.2290 | 0.9069 | 0.8516 | 0.8046 | 1188.2 |
| H10 graph-file + Gemini Lite rerank | 100 | 0.810 | 0.930 | 0.960 | 0.990 | 0.9330 | 0.1580 | 0.9090 | 0.8546 | 0.8077 | 1364.6 |

Rerank conclusion: the large historical gain came from LLM reranking, not from
the current GraphRAG candidate wrapper. H10 rerank slightly improved NDCG/MAP
over hybrid rerank on the small Gemini slice, but lost Hit@3, recall,
precision, and latency. Do not promote H10 over the local H7/H6.1 file locator
until graph topology improves. Any new rerank comparison must explicitly name
the reranker family: local Gemma/llama.cpp, dedicated local cross-encoder, or
API Gemini.
