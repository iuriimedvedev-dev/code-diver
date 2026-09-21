# CE runtime diagnosis and recovery — 2026-09-07

## Outcome

The Cross-Encoder backend itself is healthy and is serving the frozen model. The evaluation remains blocked because `localhost:18081` is owned by two different listeners by address family:

| Address | Owner | Observed behavior |
| --- | --- | --- |
| `[::1]:18081` | `kubectl --context gke-europe-west1 -n iurii-test-space port-forward svc/client 18081:8080` | KnotGate nginx/UI HTML; `POST /v1/rerank` returns `405 Not Allowed` |
| `127.0.0.1:18081` | existing `llama-server` | CE JSON API; exact rerank request returns scores |

`localhost` resolves to both `::1` and `127.0.0.1`, and the observed request selected the IPv6 listener. This is a local address-family/port collision, not a Cross-Encoder method or model failure.

## Evidence

The existing CE process was inspected without restarting it:

```text
/opt/homebrew/bin/llama-server \
  --model .code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 18081 --embedding --reranking --pooling rank \
  -b 2048 -ub 2048 -c 40960
```

The exact frozen protocol smoke used `query`, `documents`, and `top_n`:

```json
{"query":"where is the main entrypoint?","documents":["src/main.py","README.md"],"top_n":2}
```

Results:

- `POST http://localhost:18081/v1/rerank`: `405`, nginx HTML body.
- `GET http://localhost:18081/v1/models`: `200`, `text/html`, KnotGate UI HTML.
- `POST http://127.0.0.1:18081/v1/rerank`: `200`, `Server: llama.cpp`, JSON containing `results[].relevance_score` values `0.013577980920672417` and `0.0018913254607468843`.
- `GET http://127.0.0.1:18081/v1/models`: `200`, JSON identity `Qwen3-Reranker-0.6B-Q4_K_M.gguf`, `owned_by: llamacpp`.
- `curl -4 http://localhost:18081/v1/models`: the same successful CE JSON, confirming the address-family diagnosis.
- `127.0.0.1:8081`: no listener. The documented `scripts/serve_reranker.sh` default is `8081`, but the frozen evaluation explicitly uses `localhost:18081`; starting another server on `8081` would not repair this run.
- No proxy environment variables were present in the evaluation shell; probes used `--noproxy '*'`.
- Embedding identity remained `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` on `127.0.0.1:8001`.
- Qdrant `127.0.0.1:6333/collections` returned `200` with status `ok`.

## Evaluation preservation

The frozen harness has `http://localhost:18081/v1/rerank` in both its Python config override and native command. It also rejects changed frozen identities and forbids runtime service management. The existing full run was not resumed:

- run: `full-20260907-1830`
- result rows: `304/2132`
- completed matched pairs: `152`
- Python rows: `152`; Rust rows: `152`
- existing failure: Rust index `303`, retained in the denominator
- checkpoint: `next_indices=[304,305]`
- journal and manifest: not rewritten
- completed queries: not replayed
- source, application, model, and service processes: not modified

The one recorded failure remains the expected Rust CE `405` failure from the earlier run. No alternate backend or model was mixed into the retained results.

## Required recovery action

An operator owning the KnotGate port-forward must release `[::1]:18081` without changing the CE backend. The least ambiguous external fix is to rebind that port-forward to a different local port, for example `18082:8080`, while leaving the existing CE on `127.0.0.1:18081`. Alternatively, the evaluation endpoint must be explicitly changed from `localhost:18081` to `127.0.0.1:18081`, which would alter the frozen harness and requires separate authorization.

This session did not kill or restart the `kubectl` process: its PID was not created by this session, and it is an unrelated KnotGate port-forward. Credentials were not read. After `[::1]:18081` is released, rerun the exact model and POST checks above, then resume only with:

```bash
PYTHONPATH=src .venv/bin/python -B scripts/research_rust_full_eval.py \
  --run full-20260907-1830 --seconds 3000
```

The harness will preserve the existing failure and skip all completed pairs.