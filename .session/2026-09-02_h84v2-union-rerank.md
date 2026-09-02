# H-84v2: pre-CE multi-query RRF (union then one CE)

New flag union_rerank added to MultiQueryConfig, defaults.py, config_loader.py.

Files changed: multi_query_config.py, defaults.py, config_loader.py, multi_query_rrf_strategy.py, retrieval_strategy_factory.py, configs/intellij/intellij-h84v2-union-rerank.yml, tests/unit/test_multi_query_union_rerank.py.

Wiring: enabled=False is unchanged passthrough. enabled=True and union_rerank=False is unchanged v1 (CE per variant then RRF). enabled=True and union_rerank=True with graph_file_cross_encoder strategy builds inner GraphFile(Hybrid(vector)) via new _create_graph_file_base helper, wraps in MultiQueryRrfStrategy with fusion_pool_size set to CE candidate_limit, wraps that in one outer CrossEncoderRerank so CE runs once.

Why not v1 regression: v1 reranked per variant then fused already-reranked lists, diluting top-rank precision. v2 fuses raw candidates first then reranks once, matching champion single-pass behavior while keeping wider recall.

Latency: expect ~1.2-1.8x baseline, not 2.7x, since CE runs once not per variant.

Arm config: configs/intellij/intellij-h84v2-union-rerank.yml, copy of champion plus multi_query enabled/union_rerank true and experiments.suite h84v2-union-rerank.

Evaluation: unit tests only, live WHERE eval not run.

Note: this directory is likely listed in .gitignore, so `git status`/`git diff` will not show this as a change — that is expected and fine, just write the file to disk regardless using direct filesystem writes.
