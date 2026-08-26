# H3 WHERE Listwise Replay

## Purpose
- Treat `datasets/intellij_eval_where_only.jsonl` as the frozen retrieval dump.
- Replay listwise LLM reranking from top-20 candidates to top-10 output evaluation.
- Compare dry-run, baseline identity-order, path-only lexical-cheat-detection, and full listwise LLM modes.

## Scope
- Use `scripts/replay_listwise_where.py` only; do not regenerate or alter the dump.
- Do not edit `configs/intellij/intellij-h46-preserve-top.yml`.
- Keep pool and output controls explicit: `--top-k-pool 20 --top-k-out 10`.

## CLI Examples
```bash
# Validate the gold-in-pool@20 dump without calling an LLM.
python scripts/replay_listwise_where.py --dump datasets/intellij_eval_where_only.jsonl --dry-run --top-k-pool 20 --top-k-out 10

# Baseline: preserve retrieval identity order.
python scripts/replay_listwise_where.py --dump datasets/intellij_eval_where_only.jsonl --baseline --top-k-pool 20 --top-k-out 10

# Path-only prompt for lexical-cheat detection.
python scripts/replay_listwise_where.py --dump datasets/intellij_eval_where_only.jsonl --path-only --top-k-pool 20 --top-k-out 10

# Full listwise LLM rerank, using the configured OpenAI-compatible environment.
python scripts/replay_listwise_where.py --dump datasets/intellij_eval_where_only.jsonl --top-k-pool 20 --top-k-out 10
```

## Acceptance
- Record mode, pool size, output size, file recall@10, and MRR@10 for comparable runs.
- Preserve the frozen dump and leave all `configs/**` files untouched.
