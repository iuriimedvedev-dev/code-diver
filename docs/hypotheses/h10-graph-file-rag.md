# H10 - Graph-First FileRAG

| Field | Value |
| --- | --- |
| ID | `H10` |
| Status | active, not default |
| Motivation | Test the user's proposal: replace the flat hybrid file ranker with a file graph ranker, while preserving the same H5/H6 file metadata that made the index strong. |
| Assumptions | File nodes with summary/manifest metadata plus graph propagation can improve file ordering, especially on multi-file repositories where imports/references/calls matter. |
| Index composition | Qwen3-Embedding-0.6B local embeddings over `file_summary` and `file_manifest`; graph artifact over the same items. CodeSearchNet graph currently has only summary-to-manifest edges after filtering false reference edges. |
| Search/ranking flow | Query -> base hybrid seeds from file metadata -> file graph propagation -> file-level candidate ranking -> Gemini 3.1 Flash Lite rerank over file summaries -> top files. |
| Model/provider matrix | Embedding: `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` through local OpenAI-compatible runtime. Reranker: Vertex `gemini-3.1-flash-lite`. |
| Dataset | `.code-diver/tmp/codesearchnet_python_100.jsonl`, 100 public CodeSearchNet/MTEB Python cases, one expected file per query. |
| Metrics | Baseline H5/H6 `hybrid_rerank`: Hit@1 `0.860`, Hit@3 `0.930`, Hit@5 `0.960`, Hit@10 `0.960`, NDCG@10 `0.9153`, MAP@10 `0.9003`, mean `1446.7 ms`. H10 after fixes: Hit@1 `0.870`, Hit@3 `0.960`, Hit@5 `0.960`, Hit@10 `0.960`, NDCG@10 `0.9229`, MAP@10 `0.9100`, mean `2002.8 ms`. |
| Cost/latency/index-size | H10 is slower on this slice because it still runs Gemini rerank and adds graph/catalog work. Reindex of 2,000 file-level items took about `36 s`; index artifact `44-46 MB`, graph artifact about `2 MB`. |
| Result summary | The initial H10 run failed because `file_summary`/`file_manifest` were treated as real symbols, creating 2,000 false `references` edges and a mega-hub into `python/0001...`; Hit@1 dropped to `0.710`. After filtering non-symbol metadata kinds and preferring `file_summary` as rerank evidence, H10 slightly beat baseline quality on 100 cases but remained slower. |
| Decision | Keep H10 active for multi-file repository experiments, but do not promote it over the current calibrated hybrid default yet. On single-snippet CodeSearchNet, graph has little real topology; its value should be judged on repositories with imports, references, calls, and package structure. |
| Failure modes | Bad graph edges create hub effects; file-level graph collapse can hide useful summary text if manifest is selected as the representative; graph propagation can add related-but-wrong files when topology is weak. |
| Follow-ups | Add graph edge quality metrics, gate graph propagation when graph density/topology is weak, test H10 on Protogen/IntelliJ answer-set cases, and compare graph-first with hybrid-plus-graph-signal under identical reranker/candidate limits. |
| Links | `configs/benchmarks/codesearchnet-h10-graph-file-qwen-quality-100.yml`, `.code-diver/traces/codesearchnet-h10-graph-file-qwen-quality-100.jsonl`, `src/code_diver/strategies/graph_file_retrieval_strategy.py`, `src/code_diver/graph/code_graph_builder.py` |
