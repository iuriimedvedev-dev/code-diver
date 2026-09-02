# Test Result

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0 -- /Users/iurii.medvedev/Work/code-diver/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /Users/iurii.medvedev/Work/code-diver
configfile: pyproject.toml
plugins: anyio-4.14.2
collecting ... collected 1373 items / 1325 deselected / 48 selected

tests/unit/test_config_loader.py::test_config_loader_defaults_persistent_search_runtime_to_false PASSED [  2%]
tests/unit/test_config_loader.py::test_config_loader_loads_persistent_search_runtime PASSED [  4%]
tests/unit/test_config_loader.py::test_config_loader_loads_fan_out_probe_workers_and_parallel_mode PASSED [  6%]
tests/unit/test_config_loader.py::test_config_loader_maps_yaml_to_typed_config PASSED [  8%]
tests/unit/test_config_loader.py::test_config_loader_does_not_force_default_model_for_custom_embedding_provider PASSED [ 10%]
tests/unit/test_config_loader.py::test_config_loader_rejects_non_mapping_yaml PASSED [ 12%]
tests/unit/test_config_loader.py::test_config_loader_rejects_invalid_list_shape PASSED [ 14%]
tests/unit/test_config_loader.py::test_config_loader_hypothesis_overrides_inherit_base_sections PASSED [ 16%]
tests/unit/test_config_loader.py::test_config_loader_preserves_named_generation_response_format PASSED [ 18%]
tests/unit/test_config_loader.py::test_config_loader_uses_clickhouse_password_env_when_not_configured PASSED [ 20%]
tests/unit/test_config_loader.py::test_llm_rerank_generation_defaults_to_the_app_generation_block PASSED [ 22%]
tests/unit/test_config_loader.py::test_llm_rerank_generation_overrides_only_the_named_keys PASSED [ 25%]
tests/unit/test_config_loader.py::test_graph_file_frontier_limit_is_unset_by_default PASSED [ 27%]
tests/unit/test_config_loader.py::test_graph_file_frontier_limit_is_independent_of_neighbor_limit PASSED [ 29%]
tests/unit/test_config_loader.py::test_cross_encoder_preserve_top_depth_defaults_to_one PASSED [ 31%]
tests/unit/test_config_loader.py::test_cross_encoder_preserve_top_depth_is_read_from_the_config PASSED [ 33%]
tests/unit/test_config_loader.py::test_graph_file_seed_score_parity_is_off_by_default PASSED [ 35%]
tests/unit/test_config_loader.py::test_graph_file_seed_score_parity_is_read_from_the_config PASSED [ 37%]
tests/unit/test_config_loader.py::test_h81_fusion_width_flags_are_off_by_default PASSED [ 39%]
tests/unit/test_config_loader.py::test_h81_fusion_width_flags_are_read_from_the_config PASSED [ 41%]
tests/unit/test_config_loader.py::test_llm_rerank_chunking_is_unset_by_default PASSED [ 43%]
tests/unit/test_config_loader.py::test_llm_rerank_chunk_keep_is_independent_of_rerank_limit PASSED [ 45%]
tests/unit/test_embedding_token_window_config.py::test_config_loader_defaults_when_option_absent PASSED [ 47%]
tests/unit/test_embedding_token_window_config.py::test_config_loader_reads_token_window_options PASSED [ 50%]
tests/unit/test_multi_query_rrf_strategy.py::test_weighted_rrf_exact_math PASSED [ 52%]
tests/unit/test_multi_query_rrf_strategy.py::test_original_weight_can_outrank_rewrite PASSED [ 54%]
tests/unit/test_multi_query_rrf_strategy.py::test_one_variant_is_identity_passthrough PASSED [ 56%]
tests/unit/test_multi_query_rrf_strategy.py::test_fusion_pool_overfetches_each_variant_and_fusion_pool PASSED [ 58%]
tests/unit/test_multi_query_rrf_strategy.py::test_factory_disabled_and_enabled_wrapping PASSED [ 60%]
tests/unit/test_multi_query_rrf_strategy.py::test_factory_union_rerank_only_changes_graph_file_cross_encoder PASSED [ 62%]
tests/unit/test_multi_query_rrf_strategy.py::test_loader_reads_multi_query_config PASSED [ 64%]
tests/unit/test_multi_query_rrf_strategy.py::test_deterministic_rewrite_behaviors PASSED [ 66%]
tests/unit/test_multi_query_rrf_strategy.py::test_parallel_and_sequential_results_are_identical PASSED [ 68%]
tests/unit/test_multi_query_rrf_strategy.py::test_duplicate_path_counted_once_per_ranked_list PASSED [ 70%]
tests/unit/test_multi_query_union_rerank.py::test_multi_query_config_union_rerank_defaults_to_false PASSED [ 72%]
tests/unit/test_multi_query_union_rerank.py::test_factory_keeps_cross_encoder_inside_multi_query_by_default PASSED [ 75%]
tests/unit/test_multi_query_union_rerank.py::test_factory_union_rerank_wraps_multi_query_before_one_cross_encoder PASSED [ 77%]
tests/unit/test_multi_query_union_rerank.py::test_rrf_overfetches_each_variant_and_respects_effective_limit PASSED [ 79%]
tests/unit/test_multi_query_union_rerank.py::test_rrf_without_fusion_pool_requests_exact_limit PASSED [ 81%]
tests/unit/test_multi_query_union_rerank.py::test_factory_disabled_multi_query_is_bit_exact_passthrough PASSED [ 83%]
tests/unit/test_retrieval_strategy_factory_graph_file_cross_encoder.py::test_graph_file_cross_encoder_reranks_graph_file_candidates PASSED [ 85%]
tests/unit/test_retrieval_strategy_factory_graph_file_cross_encoder.py::test_graph_file_rerank_keeps_its_graph_file_base PASSED [ 87%]
tests/unit/test_retrieval_strategy_factory_graph_file_cross_encoder.py::test_cross_encoder_rerank_still_sits_on_plain_hybrid PASSED [ 89%]
tests/unit/test_retrieval_strategy_factory_graph_file_cross_encoder.py::test_union_rerank_fuses_graph_file_candidates_before_one_cross_encoder PASSED [ 91%]
tests/unit/test_retrieval_strategy_factory_graph_file_cross_encoder.py::test_union_rerank_executes_ce_less_variants_and_one_outer_rerank PASSED [ 93%]
tests/unit/test_retrieval_strategy_factory_graph_file_cross_encoder.py::test_union_rerank_false_keeps_v1_cross_encoder_inside_multi_query PASSED [ 95%]
tests/unit/test_retrieval_strategy_factory_rerank_model.py::test_rerank_generation_config_is_the_same_object_without_an_override PASSED [ 97%]
tests/unit/test_retrieval_strategy_factory_rerank_model.py::test_rerank_generation_config_swaps_the_generation_block PASSED [100%]

===================== 48 passed, 1325 deselected in 1.04s ======================
```

## Full suite run

- Passed: 1372
- Failed: 1
- Errors: 0
- Failed/errored tests: `tests/unit/test_validate_eval_dataset.py::test_validate_eval_dataset_reports_errors_and_warnings`
- This is a known/expected/acceptable failure related to `validate_eval_dataset`.
