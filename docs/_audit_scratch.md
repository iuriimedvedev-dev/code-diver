# Repository Audit Scratch

## Git Status

```text
## h37-external-validation
```

## Leftover Docs Scratch Files

```text
No files found matching docs/*scratch*
```

## `git diff pyproject.toml`

```text
```

## Unit Pytest Output

Command: `pytest tests/unit`

```text
ERROR tests/unit/test_ai_codebase_scanner.py
ERROR tests/unit/test_ai_index_response_parser.py
ERROR tests/unit/test_answer_candidate_cross_encoder_reranker.py
ERROR tests/unit/test_answer_candidate_reranker_factory.py
ERROR tests/unit/test_answer_evaluator.py
ERROR tests/unit/test_answer_grounding_metrics.py
ERROR tests/unit/test_answer_judge_abstention.py
ERROR tests/unit/test_answer_metrics_judge_aggregation.py
ERROR tests/unit/test_answer_pairwise_judge.py
ERROR tests/unit/test_answer_prompt_citation_allowlist.py
ERROR tests/unit/test_answer_report_integrity.py
ERROR tests/unit/test_answer_report_presentation.py
ERROR tests/unit/test_antigravity_sdk_generation_provider.py
ERROR tests/unit/test_benchmark_embedding_models.py
ERROR tests/unit/test_benchmark_profiles.py
ERROR tests/unit/test_cli_helpers.py
ERROR tests/unit/test_clickhouse_metrics_repository.py
ERROR tests/unit/test_code_graph_builder.py
ERROR tests/unit/test_code_symbol_extractor.py
ERROR tests/unit/test_experiment_metrics_mapper.py
ERROR tests/unit/test_experiment_runner.py
ERROR tests/unit/test_postrank_cross_encoder.py
ERROR tests/unit/test_postrank_h2_runner.py
ERROR tests/unit/test_qdrant_runtime_manager.py
ERROR tests/unit/test_replay_pool_recall.py
ERROR tests/unit/test_run_postrank_h2_deterministic_naming.py
ERROR tests/unit/test_runtime_setup.py
ERROR tests/unit/test_search_runtime.py
!!!!!!!!!!!!!!!!!!! Interrupted: 29 errors during collection !!!!!!!!!!!!!!!!!!!
======================== 1 skipped, 29 errors in 0.97s =========================
```

The direct unit run was blocked during collection because the repository is not installed in the system Python environment and required packages such as `questionary` are unavailable. `uv run pytest tests/unit` was also blocked before execution because the configured macOS `vllm-metal` wheel URL returns HTTP 404.

## Audit Result

No source or configuration changes were made. No leftover docs scratch files were present before this report was created.
