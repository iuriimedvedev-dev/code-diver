# H-86 Agentic Champion

Purpose: the new config runs the existing WHERE-78 agent/fan-out hypotheses on the current champion search stack (H-77 `seed_score_parity` + H-83 two-pass cross-encoder rerank).

## Copied Champion Settings

- `search.strategy`: `graph_file_cross_encoder`
- Collection: `intellij_h66b_budget_qwen`
- `hybrid_search` settings: candidate and lexical limits, champion lane weights, vector kind limits/multipliers, routing, BM25 scoring, weighted fusion, vector-top preservation, score margin, item-kind weights, and token length
- `graph_file_search`: champion seed/lexical limits, lane weights, graph expansion, decay, neighbor limit, and `seed_score_parity: true`
- `cross_encoder_rerank`: Qwen3 reranker endpoint and limits, including `second_pass_enabled: true`, `second_pass_score_floor: 0.3`, `second_pass_max_document_chars: 2400`, and `second_pass_candidate_cap: 24`
- Embedding config: local OpenAI-compatible Qwen3 embedding model, 128 batch size, 4 workers, and 500-character input limit
- Scanner compact budget: scanner indexing with `file_summary_compact_budget: true` and file summary/manifest chunks enabled
- Routing: `hybrid_search.routing_enabled: true`

## Hypothesis Overrides

Comparison with `configs/intellij/intellij-h74-agentic-where.yml` shows that the selected hypothesis definitions are unchanged. No hypothesis-level overrides were necessary.

## Commands

```bash
python -m code_diver --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h76_union_ce_q4
```
(H-76 arm C: 4 CE-less probes, one cross-encoder pass over the candidate union.)

```bash
python -m code_diver --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h75_fanout_champion_llmrerank_monotonic
```
(H-75 arm B: champion fan-out + RRF merge, then LLM rerank over the fused pool.)

```bash
python -m code_diver --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h74_agentic_h3_gpt4omini
```
(H-74 baseline agentic: gpt-4o-mini via LiteLLM, multi-round H3 search + verify + rerank.)

This only documents commands to run later; no evaluation was executed. YAML + session note only, per task scope.
---
# H-86 Agentic + Champion Search Session Note

## Purpose

`configs/intellij/intellij-h86-agentic-champion.yml` runs the existing WHERE-78 agent/fan-out
hypotheses (originally defined in `intellij-h74-agentic-where.yml`) on top of the CURRENT
champion search stack (H-77 `seed_score_parity` + H-83 two-pass cross-encoder rerank), as
defined in `intellij-h66b-champion.yml`. This is NOT a new search-flag experiment — it is a
reuse of the champion retrieval configuration, verbatim, under the agent/fan-out hypotheses.

## Champion search flags/sections copied verbatim from `intellij-h66b-champion.yml`

- `search.strategy`
- `collection`: `intellij_h66b_budget_qwen`
- `hybrid_search` settings
- `graph_file_search` (including `seed_score_parity` — H-77)
- `cross_encoder_rerank` (including all `second_pass_*` two-pass CE settings — H-83)
- `embedding` config
- `scanner` compact budget
- `routing`

## Hypothesis-level overrides

- Hypothesis definitions (`h74_agentic_h3_gpt4omini`, `h74_parallel_oneshot_rerank_gpt4omini`,
  `h75_fanout_champion_rrf_monotonic`, `h75_fanout_champion_llmrerank_monotonic`,
  `h76_union_ce_q4`, `h76_union_ce_q6`) plus shared `tools`, `fan_out_fusion`, and model configs
  were copied verbatim from `intellij-h74-agentic-where.yml`, preserving exact hypothesis names
  so `evaluate-search-tools --hypothesis <name>` keeps working.
- Any hardcoded collection/strategy values inside those hypothesis blocks that did not already
  point at the champion collection (`intellij_h66b_budget_qwen`) / champion strategy were
  overridden to match the champion retrieval stack, so every hypothesis in the new file runs
  against the same champion search configuration.

## Evaluation settings

- `evaluation.dataset`: `datasets/intellij_eval_where_only.jsonl`
- `evaluation.limit`: `10`
- `evaluation.workers`: `2` (kept at 2 instead of 4, since cross-encoder rerank runs as a single
  local server and shouldn't be hit concurrently by more workers)
- `experiments.suite`: `h86-agentic-champion`

## Commands to run later (NOT executed as part of this change)

```bash
evaluate-search-tools --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h76_union_ce_q4
```
Pre-CE union — closest to H-84v2 at the agent layer.

```bash
evaluate-search-tools --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h75_fanout_champion_llmrerank_monotonic
```

```bash
evaluate-search-tools --config configs/intellij/intellij-h86-agentic-champion.yml --hypothesis h74_agentic_h3_gpt4omini
```
True tool loop + read.

## Status

This note only documents the commands to run later. No evaluation was executed as part of this
change — YAML config + session note only, per task scope.
---
