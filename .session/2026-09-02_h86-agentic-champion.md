# H-86 Agentic Champion

## Purpose

New config runs the existing WHERE-78 H-74/H-75/H-76 agent/fan-out hypotheses on the current champion stack: H-77 `seed_score_parity` + H-83 two-pass CE.

## Copied Champion Flags/Sections

- `search.strategy`
- `collection` `intellij_h66b_budget_qwen`
- `hybrid_search` settings
- `graph_file_search`, including `seed_score_parity`
- `cross_encoder_rerank`, including all `second_pass_*` two-pass CE settings
- `embedding` config
- scanner compact budget
- routing

## Hypothesis Overrides

No hypothesis-level overrides were necessary. The six hypothesis definitions, names, tools, fan-out fusion, generation models, and details are copied unchanged from H-74.

## Commands

```bash
uv run code-diver --config configs/intellij/intellij-h86-agentic-champion.yml experiment --hypothesis h76_union_ce_q4 --json
```

```bash
uv run code-diver --config configs/intellij/intellij-h86-agentic-champion.yml experiment --hypothesis h75_fanout_champion_llmrerank_monotonic --json
```

```bash
uv run code-diver --config configs/intellij/intellij-h86-agentic-champion.yml experiment --hypothesis h74_agentic_h3_gpt4omini --json
```

Commands are documented for later. No evaluation was executed; this change contains YAML + session note only.
