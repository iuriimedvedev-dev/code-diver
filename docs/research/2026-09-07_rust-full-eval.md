# Rust/Python full evaluation — 2026-09-07

## Final result — truthful IPv4 full schedule

The manifest-backed run `full-20260907-2012-ipv4-actual` is complete: `2132/2132` result rows, `1066` matched Python/Rust pairs, every schedule index present exactly once, checkpoint `next_indices=[]`, and zero failures in both arms. The original `full-20260907-1830` manifest and journal were not modified. The final journal SHA-256 is `028932fcbe2352f9d0f9b4e8b9b41c05ac7cd89c9baea41a10146606b4fc3e83`; the frozen manifest SHA-256 remains `9e30e879ae02f807082eb5368794d8e89fe0697046be81b8ba7ab34f13986767`.

| Membership | Arm | Attempted / expected | Failures | Hit@10 | MRR@10 | Request-wall p50 ms | Request-wall p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| `full1065` | Python | `1065 / 1065` | `0` | `0.883568` | `0.853954` | `7958.35` | `13018.90` |
| `full1065` | Rust | `1065 / 1065` | `0` | `0.839437` | `0.690823` | `6224.73` | `9888.39` |
| `WHERE78` | Python | `78 / 78` | `0` | `0.871795` | `0.706553` | `7481.67` | `12411.82` |
| `WHERE78` | Rust | `78 / 78` | `0` | `0.794872` | `0.399547` | `5679.64` | `10147.00` |
| `mech150` | Python | `150 / 150` | `0` | `0.893333` | `0.880000` | `7707.92` | `12731.53` |
| `mech150` | Rust | `150 / 150` | `0` | `0.866667` | `0.721968` | `5709.11` | `9573.14` |
| `mech_file229` | Python | `229 / 229` | `0` | `0.882096` | `0.817079` | `7682.85` | `12411.82` |
| `mech_file229` | Rust | `229 / 229` | `0` | `0.838428` | `0.608995` | `5744.97` | `9772.67` |

Paired Rust-minus-Python deltas are: `full1065` Hit@10 `-0.044131`, MRR `-0.163131`; `WHERE78` Hit@10 `-0.076923`, MRR `-0.307005`; `mech150` Hit@10 `-0.026667`, MRR `-0.158032`; and overlapping `mech_file229` Hit@10 `-0.043668`, MRR `-0.208084`. `mech_file229` is an overlapping membership view of the source mech file, not an independent holdout.

The effective routes recorded in the unchanged truthful manifest were CE `http://127.0.0.1:51671/v1/rerank`, Qdrant `http://127.0.0.1:6333`, and embedding `http://localhost:8001/v1/embeddings`. Before and during the run, direct CE and forwarded exact requests returned HTTP `200`, model `Qwen3-Reranker-0.6B-Q4_K_M.gguf`, and the expected `results[].relevance_score`; the owned forwarder was stopped after completion. The run used the existing binary, catalog, graph, model, and frozen identity checks without source edits or service restart.

Startup is a separate measurement and is excluded from the request-wall columns. The seven continuation chunks recorded Python initialization from `1543.40` to `2154.91 ms` and Rust initialization from `5498.05` to `6112.72 ms`; the final chunk recorded `1709.20 ms` and `5990.54 ms`, respectively. Rust request wall includes the persistent native server request boundary, while Python request wall excludes one-time initialization; these are not end-to-end latency claims. The only warning during chunks was the unauthenticated Hugging Face Hub warning (`HF_TOKEN` unset), not an evaluation failure.

### Provenance correction for historical index `624`

The original `full-20260907-1830` journal is unchanged and contains exactly `304` result rows for indices `0..303`; its only failure is Rust index `303` (`CE HTTP 405`). Index `624` is **not** in that original journal. It is recorded first in the copied continuation `full-20260907-2012-ipv4`, where Rust case `where-editor-caret` failed on a Qdrant request to `http://localhost:6333`; the same inherited history appears in the complete `full-20260907-2012-ipv4-qdrant` directory. Neither directory is alternate-route evidence: the initial wrapper patched the copied `runpy` dictionary rather than the harness functions' actual globals. The truthful `full-20260907-2012-ipv4-actual` journal is a separate manifest-backed journal, not a rewrite or merge of the original journal; it contains neither historical failure and completed every scheduled attempt successfully. No historical failure was silently removed from any journal.

## Historical partial recovery status — before completion

The required IPv4 route was verified and a fresh, manifest-backed continuation was run without changing source files or any service. The dedicated forwarder was `127.0.0.1:51671 -> 127.0.0.1:18081`; the actual continuation also used explicit `http://127.0.0.1:6333` for Qdrant. The CE route returned `HTTP 200` for both `GET /v1/models` and the exact native `POST /v1/rerank` request, with model `Qwen3-Reranker-0.6B-Q4_K_M.gguf` and `results[].relevance_score`.

The truthful alternate-route run is `full-20260907-2012-ipv4-actual`. It completed `380/2132` result rows (`190` matched pairs), with checkpoint `next_indices=[380,381]` and zero failures. This is a partial continuation, not a final full-dataset result. Its endpoint manifest records CE `http://127.0.0.1:51671/v1/rerank`, Qdrant `http://127.0.0.1:6333`, and the unchanged embedding endpoint `http://localhost:8001/v1/embeddings`.

| Membership | Arm | Attempted / expected | Failures | Hit@10 | MRR@10 | p50 wall ms | p95 wall ms |
|---|---|---:|---:|---:|---:|---:|---:|
| `full1065` | Python | `190 / 1065` | `0` | `0.884211` | `0.852719` | `8577.71` | `15185.55` |
| `full1065` | Rust | `190 / 1065` | `0` | `0.863158` | `0.729517` | `6676.48` | `10745.84` |
| `WHERE78` | Python | `10 / 78` | `0` | `0.900000` | `0.758333` | `7409.81` | `13220.43` |
| `WHERE78` | Rust | `10 / 78` | `0` | `0.900000` | `0.558333` | `4512.70` | `11776.84` |
| `mech150` | Python | `32 / 150` | `0` | `0.843750` | `0.828125` | `7948.36` | `13741.57` |
| `mech150` | Rust | `32 / 150` | `0` | `0.843750` | `0.645833` | `5247.28` | `10285.65` |

The `mech_file229` overlapping view is `42/229` per arm, zero failures, Hit@10 `0.857143` for both, Python MRR `0.811508`, and Rust MRR `0.625000`. These are overlapping membership views, not additional unique attempts, and must not be presented as independent holdout evidence.

The exact fresh-run invocation used an in-memory wrapper around the harness module. The wrapper patched the functions' actual `__globals__` (not the copied `runpy` return dictionary), so the manifest and native command contain the effective routes:

```bash
PYTHONPATH=src:scripts .venv/bin/python -B -c 'import dataclasses,runpy,sys; m=runpy.run_path("scripts/research_rust_full_eval.py",run_name="rust_eval_wrapper"); g=m["main"].__globals__; old_config=g["config"]; old_get_json=g["get_json"]; ce="http://127.0.0.1:51671/v1/rerank"; ce_models="http://127.0.0.1:51671/v1/models"; qdrant="http://127.0.0.1:6333"; g["config"]=lambda: (lambda c: dataclasses.replace(c,storage=dataclasses.replace(c.storage,qdrant=dataclasses.replace(c.storage.qdrant,url=qdrant)),cross_encoder_rerank=dataclasses.replace(c.cross_encoder_rerank,url=ce)))(old_config()); g["get_json"]=lambda url: old_get_json((qdrant+url[len("http://localhost:6333"):]) if url.startswith("http://localhost:6333") else (ce_models if url == "http://localhost:18081/v1/models" else url)); g["COMMAND"]=[g["BIN"],"--server","--catalog","/tmp/rust_catalog.jsonl","--graph","/tmp/rust_graph.jsonl","--model",g["MODEL"],"--embedding-url","http://localhost:8001/v1/embeddings","--qdrant-url",qdrant,"--ce-url",ce,"--retrieval-limit","360","--candidate-limit","34","--limit","10"]; sys.argv=["research_rust_full_eval.py","--run","full-20260907-2012-ipv4-actual","--seconds","3000"]; g["main"]()'
```

To continue only the pending suffix, use the same command and change only `--run`/the `sys.argv` value if a new run name is required; for this immutable continuation retain `full-20260907-2012-ipv4-actual` and omit `--max-pairs`. The latest artifacts are under `artifacts/research/2026-09-07_rust-full-eval/full-20260907-2012-ipv4-actual/`; the manifest SHA-256 is `9e30e879ae02f807082eb5368794d8e89fe0697046be81b8ba7ab34f13986767` and the journal SHA-256 is `36fdcfbb27259d1968ce8a7aa5b8a412e57fe70e0cf6475865be9cb44e04ee618`.

### Provenance correction for the earlier apparent IPv4 continuation

The earlier directory `full-20260907-2012-ipv4-qdrant` contains a complete `2132/2132` schedule, but it is **not** alternate-route evidence. The first runtime wrapper patched the dictionary returned by `runpy.run_path()` rather than the harness functions' actual globals; its manifest therefore correctly records the original `localhost` command, and its results are retained only as original-route evidence. It must not be described as an IPv4 rerun or combined with the truthful IPv4 partial metrics. The original manifest and `304`-result journal under `full-20260907-1830` were not modified.

## Historical status before IPv4 completion

**Historical blocked state; superseded by the final truthful IPv4 run above.** The original resumable harness started successfully, passed its frozen-identity checks, and completed `304/2132` result rows (`152` Python and `152` Rust). It stopped at the first Cross-Encoder service/protocol failure; that original run was not resumed or rewritten.

The planned schedule contains `1066` unique paired cases, or `2132` arm attempts, for the union of the datasets. The memberships are `full1065=1065`, `WHERE78=78`, `mech150=150`, and `mech_file229=229`; the latter is an accounting view of the source mech file and overlaps the other memberships. The current checkpoint is:

```text
completed: 304/2132
next_indices: [304, 305]
run: full-20260907-1830
```

## Historical previous result recovered

The earlier bounded diagnostic completed `12/12` arms with zero failures on three known WHERE cases repeated twice per arm. It reported Python `Hit@10=1.000000`, `MRR=1.000000`, and Rust `Hit@10=1.000000`, `MRR=0.833333`; the Rust MRR difference was the daemon case at rank `2` versus Python rank `1`. This was not an independent holdout and was not reused as full-evaluation evidence. The release binary identity in that diagnostic is SHA-256 `7c54b8750d4c327a19b8045577837eac09e784d61658d76bf0033ed1efcf9724`.

## Checks and commands

Harness unit tests passed:

```text
PYTHONPATH=src:scripts .venv/bin/python -B scripts/test_research_rust_full_eval.py
Ran 4 tests in 0.002s
OK
```

The required services responded before the run: Qdrant on `localhost:6333`, embeddings on `localhost:8001`, and CE on `localhost:18081`. The endpoint manifest recorded embedding model `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` and CE model `Qwen3-Reranker-0.6B-Q4_K_M.gguf`. No service was started, restarted, or otherwise modified.

The isolated smoke run completed `4/4` attempts (`2` pairs) with no failures:

```text
PYTHONPATH=src .venv/bin/python -B scripts/research_rust_full_eval.py \
  --run smoke-20260907-1830 --seconds 3000 --max-pairs 2
```

The full run was then started exactly as a finite resumable chunk:

```text
PYTHONPATH=src .venv/bin/python -B scripts/research_rust_full_eval.py \
  --run full-20260907-1830 --seconds 3000
```

## Frozen identities

The full manifest froze the exact configuration, source/data schedule, endpoints, and runtime identity. Relevant SHA-256 values are:

| Artifact | SHA-256 |
|---|---|
| `native/code_diver_search_bin/target/release/code_diver_search_bin` | `7c54b8750d4c327a19b8045577837eac09e784d61658d76bf0033ed1efcf9724` |
| `artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt` | `8dcadfdc02b050fd35ebafca7f436c822859ff38cfeba4f9bd1203abc90e5010` |
| `/tmp/rust_catalog.jsonl` | `e32b2d12539b914bdff33a4d1935d4d4597ac43940f6925d450519f9222cbf3e` |
| `/tmp/rust_graph.jsonl` | `4c89a44094bbc6c71a2d34751e7dabeb9f5c7685719051f1876b743dfa6f2cf3` |
| `.code-diver/intellij-h37-jvm-graph.json` | `05eeb075acc8c4f3e13c1c578cf4a3e8ac2f04d26cf031d8bb04ca605a35865d` |

The configuration was `configs/intellij/intellij-h91a-meta-ranker.yml`, with in-memory endpoint overrides and native retrieval limit `360`, candidate limit `34`, and result limit `10`. The manifest seed is `42`; its recorded Git head is `d1c506407b5bc08c053c882e5449bf1fed5d8819`.

## Historical new partial results

The numbers below are descriptive for the completed prefix only. They are not final full-dataset metrics.

| Membership | Arm | Attempted / expected | Failures | Hit@10 | MRR@10 | p50 wall ms | p95 wall ms |
|---|---|---:|---:|---:|---:|---:|---:|
| `full1065` | Python | `152 / 1065` | `0` | `0.907895` | `0.879496` | `6237.84` | `10262.50` |
| `full1065` | Rust | `152 / 1065` | `1` | `0.875000` | `0.748849` | `4110.80` | `8040.22` |
| `WHERE78` | Python | `7 / 78` | `0` | `1.000000` | `0.892857` | `4348.48` | `7382.61` |
| `WHERE78` | Rust | `7 / 78` | `0` | `1.000000` | `0.654762` | `3314.30` | `5544.06` |
| `mech150` | Python | `25 / 150` | `0` | `0.920000` | `0.920000` | `6476.40` | `9856.61` |
| `mech150` | Rust | `25 / 150` | `0` | `0.920000` | `0.693333` | `4011.42` | `7719.95` |

The overlapping `mech_file229` membership had `32/229` attempts per arm, with zero failures; its Python/Rust Hit@10 values were both `0.937500`, and MRR values were `0.914063` and `0.684896`. For the completed `full1065` prefix, the paired Rust-minus-Python deltas are `-0.032895` Hit@10 and `-0.130647` MRR. The slice counts are overlapping membership views, not additional unique attempts; the journal has exactly `304` result rows, representing `152` completed matched pairs. Python initialization was `1514.68 ms`, Rust initialization was `5386.59 ms`, and both are recorded separately from per-request wall time.

## Historical exact blocker

The native server exited while processing result index `303`, Rust arm, case `config-platform-execution-process-mediator-common-module-content.yaml`. Its stderr contains:

```text
Error: "CE HTTP 405 Method Not Allowed: <html>...
<center><h1>405 Not Allowed</h1></center>
... nginx ..."
```

The journal records the same `RuntimeError` and marks that attempt as a failure. The harness then raised `RuntimeError: Native process exited; stop chunk, resume remaining attempts`. This is a service/protocol failure, not a source-hash mismatch, checkpoint corruption, or application-code result. Do not resume this run until the CE service/protocol issue is independently fixed and verified; do not reset or rewrite the journal.

The run emitted the expected unauthenticated Hugging Face Hub warning during initialization; it was not the cause of the stop.

## Historical follow-up CE verification

The requested bounded, non-mutating follow-up was run before any resume. The native client path and request schema were read directly from `native/code_diver_search_bin/src/embedding.rs`: `POST http://localhost:18081/v1/rerank` with JSON keys `query`, `documents`, and `top_n`, expecting `results[].relevance_score`.

At `2026-09-07 17:05:34` the exact minimal request shape still returned:

```text
HTTP/1.1 405 Not Allowed
Server: nginx
Content-Type: text/html
```

with the nginx HTML body containing `405 Not Allowed`. A `GET /v1/models` returned `200 OK` but served the KnotGate web UI HTML (`Content-Type: text/html`), not a model-list JSON response. A `HEAD /v1/rerank` also returned `200 OK` for the same UI HTML route; this does not validate the required POST protocol. The previously recorded CE identity was `Qwen3-Reranker-0.6B-Q4_K_M.gguf`, but that identity is not currently observable from the live endpoint, so the expected identity is treated as unavailable/different.

No benchmark query was retried, including failed index `303`; no full-evaluation chunk was started; no cache, journal, manifest, checkpoint, source, configuration, or service was modified. The journal remains `304/2132` result rows (`152` Python and `152` Rust), with checkpoint `next_indices=[304, 305]`. The run therefore remains persistently blocked, and the existing Rust failure at index `303` remains in the denominator.

## Evidence paths

- Full manifest: `artifacts/research/2026-09-07_rust-full-eval/full-20260907-1830/manifest.json`
- Full journal: `artifacts/research/2026-09-07_rust-full-eval/full-20260907-1830/results.jsonl`
- Full checkpoint: `artifacts/research/2026-09-07_rust-full-eval/full-20260907-1830/checkpoints.jsonl`
- Full summary: `artifacts/research/2026-09-07_rust-full-eval/full-20260907-1830/summary-1788798798694657000.json`
- Native stderr: `artifacts/research/2026-09-07_rust-full-eval/full-20260907-1830/native-1788798798694657000.stderr`
- Endpoint identities: `artifacts/research/2026-09-07_rust-full-eval/full-20260907-1830/endpoints-1788798798694657000.json`
- Smoke evidence: `artifacts/research/2026-09-07_rust-full-eval/smoke-20260907-1830/`

## Historical limitations

No final `full1065`, `WHERE78`, or `mech150` evaluation claim can be made from this run. The evaluation remains exposed to the known95 tuning/training data, so it is not an independent holdout claim. Wall-time comparisons also retain the harness boundary caveat: Python and Rust initialization are measured separately, while Rust request wall time includes the persistent native server request boundary and Python request wall time excludes one-time initialization.