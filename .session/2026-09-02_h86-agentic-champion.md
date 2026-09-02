# H-86 Agentic + Champion Search Session Note

## Purpose

configs/intellij/intellij-h86-agentic-champion.yml runs the existing WHERE-78 agent/fan-out hypotheses (originally defined in intellij-h74-agentic-where.yml) on top of the CURRENT champion search stack (H-77 seed_score_parity + H-83 two-pass cross-encoder rerank), as defined in intellij-h66b-champion.yml. This is NOT a new search-flag experiment.

## Champion search flags copied from intellij-h66b-champion.yml

- search.strategy
- collection: intellij_h66b_budget_qwen
- hybrid_search settings
- graph_file_search (including seed_score_parity)
- cross_encoder_rerank (including second_pass_* two-pass CE settings)
- embedding config
- scanner compact budget
- routing

## Hypothesis-level overrides

- Hypothesis definitions (h74_agentic_h3_gpt4omini, h74_parallel_oneshot_rerank_gpt4omini, h75_fanout_champion_rrf_monotonic, h75_fanout_champion_llmrerank_monotonic, h76_union_ce_q4, h76_union_ce_q6) plus shared tools, fan_out_fusion, and model configs were copied verbatim from intellij-h74-agentic-where.yml.
- Any hardcoded collection/strategy values that did not already point at intellij_h66b_budget_qwen were overridden to the champion values.

## Evaluation settings

- evaluation.dataset: datasets/intellij_eval_where_only.jsonl
- evaluation.limit: 10
- evaluation.workers: 2
- experiments.suite: h86-agentic-champion

## Commands to run later (not executed)

evaluate-search-tools --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h76_union_ce_q4

evaluate-search-tools --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h75_fanout_champion_llmrerank_monotonic

evaluate-search-tools --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h74_agentic_h3_gpt4omini

## Status

This note only documents commands to run later. No evaluation was executed as part of this change.
