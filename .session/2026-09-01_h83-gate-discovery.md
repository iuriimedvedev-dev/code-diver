# H-83 gate discovery — 2026-09-01

## Verified protocol

1. Run the same-sitting WHERE screen first: `datasets/intellij_eval_where_only.jsonl` (78 rows, verified with `wc -l`; notes refer to the pre-cleanup WHERE-79 set). Use `--limit 10 --json`, workers are fixed by the config at 1.
2. Only if the candidate improves the WHERE floor should the mechanical guard and then the full gate run. The mechanical guard is a stratified 150-case slice (50 config / 50 path / 50 symbol), conventionally `/tmp/mech150.jsonl`; it is a guard, not a substitute for the full gate.
3. The full gate is the complete answer-set dataset (1065 rows), not the 150-case slice. Promotion requires all four full-gate floors recorded in the latest promotion protocol: overall recall@10 >= 0.8292, path_symbol >= 0.8350, semantic >= 0.8021, and workflow >= 0.7638.

For H-83 specifically, the implementation note says: compare champion, H-82, and H-83 on WHERE-79; run guard + 1065 only if WHERE improves. H-83 is therefore not yet a full-gate result merely because the WHERE run won.

## Full evaluation dataset and exact CLI shape

Full JSONL path (verified in H-83 config and recent gate notes):
`/Users/iurii.medvedev/Work/code-diver/datasets/intellij_eval_1000.answer_sets.jsonl`
It contains 1065 cases despite the historical `1000` filename. The WHERE screen is:
`/Users/iurii.medvedev/Work/code-diver/datasets/intellij_eval_where_only.jsonl`.
The mechanical guard input is `/tmp/mech150.jsonl` (generated/runtime artifact; not in `datasets/`).

Exact full-gate command for this arm (from the CLI contract/config):

```bash
uv run code-diver --config configs/intellij/intellij-h83-ce-twopass.yml \
  evaluate --dataset datasets/intellij_eval_1000.answer_sets.jsonl \
  --limit 10 --json > /tmp/h83_1065.json
```

Equivalent screen/guard commands change only `--dataset`:

```bash
uv run code-diver --config configs/intellij/intellij-h83-ce-twopass.yml \
  evaluate --dataset datasets/intellij_eval_where_only.jsonl --limit 10 --json > /tmp/h83_where79.json

uv run code-diver --config configs/intellij/intellij-h83-ce-twopass.yml \
  evaluate --dataset /tmp/mech150.jsonl --limit 10 --json > /tmp/h83_mech150.json
```

`evaluate` accepts `--dataset`, `--limit`, and `--json`; `--limit` is retrieval top-k, not case count. Case count is the number of rows loaded from the selected JSONL. The config supplies `evaluation.workers: 1`, Qdrant collection, embedding/reranker endpoints, and H-83 flags. Do not add `--reindex` for this search-only run unless deliberately rebuilding the collection.

## H-83 flags/environment

`configs/intellij/intellij-h83-ce-twopass.yml` uses collection `intellij_h66b_budget_qwen`, Qdrant `http://localhost:6333`, embedder `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` at `http://127.0.0.1:8001/v1/embeddings`, and llama.cpp reranker `Qwen3-Reranker-0.6B` at `http://127.0.0.1:8081/v1/rerank`. It sets `search.strategy: graph_file_cross_encoder`, `search.limit: 10`, `evaluation.workers: 1`, `seed_score_parity: true`, and H-83 only: `second_pass_enabled: true`, floor `0.3`, expanded document chars `2400`, retry cap `24`; H-82 logit/tie flags remain off.

Recent benchmark procedure also requires keeping model services warm:
`python scripts/keep_services_warm.py --quiet` (embedder every 1s, reranker every 5s by default). Canonical launch environment includes `VLLM_HOST_IP=127.0.0.1`, `GLOO_SOCKET_IFNAME=lo0`, and `VLLM_METAL_MEMORY_FRACTION=0.3`; embedder launch is pooling on `:8001` with `--max-model-len 512`, reranker launch is embedding/reranking with `--batch-size 768 --ubatch-size 768` on `:8081`.

## Services checked by curl (2026-09-01)

- Qdrant `127.0.0.1:6333/healthz`: **200**; `/collections`: **200**.
- Embedder `127.0.0.1:8001/v1/models`: **200**.
- Reranker `127.0.0.1:8081/health`: **200**.
- ClickHouse `127.0.0.1:18123/ping`: **000/unavailable**.
- Grafana `127.0.0.1:3000/api/health`: **404** (endpoint/HTTP response does not verify health; service is not needed for retrieval evaluation).

Conclusion: the retrieval gate prerequisites (Qdrant, embedder, reranker) are available now. ClickHouse/Grafana are irrelevant because the H-83 config has metrics disabled; no code or tests were changed.
