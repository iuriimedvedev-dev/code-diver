# Rust full evaluation — session handoff

## Final actual routing and completion

- Truthful run `full-20260907-2012-ipv4-actual` completed `2132/2132` result rows (`1066` matched pairs), every index exactly once, checkpoint `next_indices=[]`, and zero failures for Python and Rust.
- Final summary: `full1065` Python/Rust Hit@10 `0.883568/0.839437`, MRR `0.853954/0.690823`; `WHERE78` `0.871795/0.794872`, MRR `0.706553/0.399547`; `mech150` `0.893333/0.866667`, MRR `0.880000/0.721968`; overlapping `mech_file229` `0.882096/0.838428`, MRR `0.817079/0.608995`. All attempted/expected counts are complete and all failures are `0`.
- Request-wall p50/p95 ms: `full1065` Python `7958.35/13018.90`, Rust `6224.73/9888.39`; `WHERE78` Python `7481.67/12411.82`, Rust `5679.64/10147.00`; `mech150` Python `7707.92/12731.53`, Rust `5709.11/9573.14`; `mech_file229` Python `7682.85/12411.82`, Rust `5744.97/9772.67`.
- Paired Rust-minus-Python deltas (Hit@10, MRR): `full1065` `(-0.044131,-0.163131)`, `WHERE78` `(-0.076923,-0.307005)`, `mech150` `(-0.026667,-0.158032)`, `mech_file229` `(-0.043668,-0.208084)`. The `mech_file229` view overlaps other memberships and is not an independent holdout.
- Effective routes were CE `http://127.0.0.1:51671/v1/rerank`, Qdrant `http://127.0.0.1:6333`, embedding `http://localhost:8001/v1/embeddings`; the frozen manifest SHA is `9e30e879ae02f807082eb5368794d8e89fe0697046be81b8ba7ab34f13986767`, final journal SHA is `028932fcbe2352f9d0f9b4e8b9b41c05ac7cd89c9baea41a10146606b4fc3e83`.
- Startup caveat: initialization was measured separately from request wall. Across continuation chunks Python startup was `1543.40..2154.91 ms`, Rust `5498.05..6112.72 ms`; final chunk was Python `1709.20 ms`, Rust `5990.54 ms`. Rust request wall includes the persistent native request boundary; Python excludes one-time initialization. HF Hub unauthenticated-request warnings were non-fatal.

## Provenance correction

- The preserved original `full-20260907-1830` journal has exactly `304` result rows, indices `0..303`, and only failure Rust index `303` (CE HTTP `405`).
- Historical index `624` is in `full-20260907-2012-ipv4` (Rust `where-editor-caret`, Qdrant send failure) and the copied complete `full-20260907-2012-ipv4-qdrant` run; it is not in the original `1830` journal. Those runs used the original-route command because the first wrapper patched the copied `runpy` dictionary rather than function `__globals__`.
- The truthful `actual` run has zero failures and was not merged with either original-route run. No failure was deleted or rewritten.

## Earlier actual routing and partial progress

- Verified CE IPv4 directly at `127.0.0.1:18081`: `GET /v1/models` and exact `POST /v1/rerank` both returned `200`; model was `Qwen3-Reranker-0.6B-Q4_K_M.gguf`.
- Started owned forwarder `127.0.0.1:51671 -> 127.0.0.1:18081`; it was used by the truthful run for both Python and Rust CE requests. Explicit Qdrant route was `127.0.0.1:6333`.
- Correct manifest-backed run: `full-20260907-2012-ipv4-actual`, `380/2132` results (`190` pairs), checkpoint `next_indices=[380,381]`, zero failures. This is partial, not final full-evaluation evidence.
- Partial `full1065`: Python `190/1065`, hit@10 `0.884211`, MRR `0.852719`; Rust `190/1065`, hit@10 `0.863158`, MRR `0.729517`; both zero failures.
- Partial `WHERE78`: `10` per arm, both hit@10 `0.900000`; Python MRR `0.758333`, Rust MRR `0.558333`, zero failures.
- Partial `mech150`: `32` per arm, both hit@10 `0.843750`; Python MRR `0.828125`, Rust MRR `0.645833`, zero failures.
- Overlapping `mech_file229`: `42` per arm, both hit@10 `0.857143`; Python MRR `0.811508`, Rust MRR `0.625000`, zero failures.
- The concrete continuation is the same in-memory wrapper recorded in the research document; retain run `full-20260907-2012-ipv4-actual` and omit `--max-pairs` to process the pending suffix.
- Important provenance correction: the earlier apparent IPv4 continuation `full-20260907-2012-ipv4-qdrant` actually used the original localhost command because its first wrapper patched the copied `runpy` dictionary, not function `__globals__`. Its complete `2132/2132` output is retained as original-route evidence only and is not merged with the actual IPv4 run.

## Prior status before final completion

- Full run `full-20260907-1830` is **blocked and intentionally stopped** after a Cross-Encoder service/protocol failure.
- Unit harness tests: `4 passed, 0 failed`.
- Isolated smoke: `4/4` attempts, `0` failures.
- Full schedule: `1066` unique paired cases / `2132` arm attempts; journal `304/2132` result rows (`152` Python, `152` Rust), or `152` completed matched pairs; checkpoint `next_indices=[304,305]`.
- Do not resume, reset, or rewrite the journal until the CE `HTTP 405 Method Not Allowed` issue is independently resolved and verified.

## New evidence

- The sole recorded failure is Rust index `303`, case `config-platform-execution-process-mediator-common-module-content.yaml`.
- Native stderr: `CE HTTP 405 Method Not Allowed` with an nginx HTML body; the native process exited and the harness stopped as designed.
- Follow-up at `2026-09-07 17:05:34`: the exact native request (`POST /v1/rerank` with `query`, `documents`, `top_n`) still returned nginx `HTTP 405 Not Allowed`; `GET /v1/models` returned KnotGate UI HTML instead of JSON, so the expected CE model identity is unavailable/different from the recorded `Qwen3-Reranker-0.6B-Q4_K_M.gguf`.
- Partial `full1065`: Python `152/1065`, hit@10 `0.907895`, MRR `0.879496`; Rust `152/1065`, one failure, hit@10 `0.875000`, MRR `0.748849`.
- Partial `WHERE78` membership: `7` attempts per arm, Python MRR `0.892857`, Rust MRR `0.654762`, both hit@10 `1.0`.
- Partial `mech150` membership: `25` attempts per arm, Python MRR `0.920000`, Rust MRR `0.693333`, both hit@10 `0.92`.
- Partial `mech_file229` membership: `32` attempts per arm, zero failures, both hit@10 `0.937500`; Python MRR `0.914063`, Rust MRR `0.684896`.
- These slice counts overlap `full1065`; the unique journal count remains `304` rows.
- Startup: Python `1514.68 ms`; Rust `5386.59 ms`.

## Prior evidence

The earlier diagnostic was `12/12` arms with zero failures on three known cases repeated twice. It reported Python MRR `1.000000` and Rust MRR `0.833333`; it was not an independent holdout. The release binary hash is `7c54b8750d4c327a19b8045577837eac09e784d61658d76bf0033ed1efcf9724`.

## Resume command after external service resolution

Do not execute until the CE service/protocol problem is fixed and a separate safe service check confirms the expected endpoint behavior:

```bash
PYTHONPATH=src .venv/bin/python -B scripts/research_rust_full_eval.py \
  --run full-20260907-1830 --seconds 3000
```

## Evidence

See `docs/research/2026-09-07_rust-full-eval.md` for the complete report. Runtime artifacts are under `artifacts/research/2026-09-07_rust-full-eval/full-20260907-1830/`; the previous clean smoke evidence is under `artifacts/research/2026-09-07_rust-full-eval/smoke-20260907-1830/`.