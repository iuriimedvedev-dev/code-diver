# Rust parity final evaluation — 2026-09-09

## Decision

Completed the requested live evaluation using the rebuilt Rust release binary and the isolated MLX Metal reranker on the M3 Max. Existing services on `8001`, `18081`, and `6333` were reused and left running. Only the owned MLX process tree on `18083` was stopped after evaluation.

## Evidence

- Native binary SHA-256: `28161f0834436006cd838b3f5ab740f34c3aa6db5fcca0d60d6c1d2b19f2a0de`.
- Smoke run `2026-09-09_parity-smoke2`: 2 pairs, zero failures on both arms; Python hit@10/MRR `1.0/1.0`, Rust `0.5/0.25`.
- Thirty-pair run `2026-09-09_parity-run30`: zero failures on both arms; Python hit@10/MRR `0.9666666667/0.9666666667`, Rust `0.7333333333/0.6111111111`.
- Thirty-pair latency: Python p50/p95 `21,907.73/94,266.22 ms`; Rust p50/p95 `23,741.84/125,080.77 ms`.
- Rust minus Python deltas: hit@10 `-0.2333333333`, MRR `-0.3555555556`, p50 `+1,834.11 ms`, p95 `+30,814.55 ms`.
- Versus `2026-09-09_external-run30`, Rust quality changed by hit@10 `-0.2000000000` and MRR `-0.2333333333`; p50 increased `+11,419.87 ms`, p95 increased `+5,005.61 ms`.
- MLX smoke latency was faster than Python, but the 30-pair end-to-end run was slower; no robust full-workload speedup is confirmed.
- Final checks: embedding HTTP `200`, Python CE HTTP `200`, Qdrant HTTP `200`, and port `18083` free.
- Harness validation: `14` tests passed.

## Artifacts

- Full report: `docs/research/2026-09-09_rust-parity-final-eval.md`.
- Smoke summary: `artifacts/research/2026-09-07_rust-full-eval/2026-09-09_parity-smoke2/summary-1788975153443029000.json`.
- Thirty-pair summary: `artifacts/research/2026-09-07_rust-full-eval/2026-09-09_parity-run30/summary-1788975335772011000.json`.

## Codebase adjustment

The evaluation harness’s binary identity guard and its corresponding test fixture were updated from the previous release hash to the measured rebuilt candidate hash so the persisted run manifest records the actual binary evaluated.
