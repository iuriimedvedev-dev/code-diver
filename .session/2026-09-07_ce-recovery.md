# CE recovery — session handoff

## Root cause

`localhost:18081` is an address-family collision. `kubectl --context gke-europe-west1 -n iurii-test-space port-forward svc/client 18081:8080` owns `[::1]:18081` and serves KnotGate nginx/UI HTML; the existing `llama-server` owns `127.0.0.1:18081` and serves the CE API. Because `localhost` resolved to IPv6 first, the frozen eval received nginx `405` for `POST /v1/rerank` and HTML for `GET /v1/models`.

## Verified runtime

- Existing CE command uses `Qwen3-Reranker-0.6B-Q4_K_M.gguf`, `--host 127.0.0.1`, `--port 18081`, `--embedding --reranking --pooling rank`.
- Direct `127.0.0.1` model identity is the expected Qwen3 filename.
- Exact `POST /v1/rerank` with `query`, `documents`, and `top_n` returns `200` JSON with `results[].relevance_score`.
- `127.0.0.1:8001` embedding identity and Qdrant `6333` remain healthy.
- No listener exists on `8081`; starting the documented default would not repair the frozen `localhost:18081` URL.

## Evaluation state

No resume was safe because the frozen script hardcodes `localhost:18081` in both Python and Rust paths. The full run remains unchanged at `304/2132` result rows (`152` pairs, `152` Python, `152` Rust), with Rust index `303` failure retained in the denominator and checkpoint `next_indices=[304,305]`. Manifest, journal, completed queries, source, and services were not modified.

## Blocker and next action

The unrelated KnotGate port-forward must release `[::1]:18081` (preferably rebind itself to another local port such as `18082`) or explicit authorization is needed to change the frozen endpoint to `127.0.0.1:18081`. This session did not kill or restart that process. Once released, repeat the direct checks and resume the existing run with `PYTHONPATH=src .venv/bin/python -B scripts/research_rust_full_eval.py --run full-20260907-1830 --seconds 3000`.