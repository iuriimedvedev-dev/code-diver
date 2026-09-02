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
