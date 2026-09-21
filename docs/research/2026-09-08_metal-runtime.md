# Metal Runtime Microbenchmark — 2026-09-08

## Scope and provenance

This document records a read-only analysis of the isolated `llama-server` experiment. No application source, root configuration, model, or service configuration was changed. The experiment compared the existing Qwen3 reranker GGUF on the unchanged baseline endpoint `127.0.0.1:18081` and an owned isolated endpoint `127.0.0.1:18082`.

The isolated server was launched with:

```bash
/opt/homebrew/bin/llama-server \
  --model .code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 18082 \
  --embedding --reranking --pooling rank \
  --batch-size 2048 --ubatch-size 2048 --ctx-size 40960 \
  --parallel 1 --device MTL0 --gpu-layers all --op-offload --metrics
```

The existing baseline had previously reported `total_slots=4`; the isolated command explicitly changed this to `parallel=1` and reported `total_slots=1`. Consequently, the timing difference is confounded by slot/concurrency configuration as well as explicit Metal settings. It is not an isolated GPU-effect measurement.

The process was stopped after the experiment. The retained command output was:

```text
18082_listening=no
baseline_health={"status":"ok"}
```

The stop check used `lsof` only for the owned port and an IPv4 health request to the untouched baseline. No server log was read.

## Frozen data selection

The payload used one fixed query and exactly these `34` tracked project files. The files were selected explicitly; this was not catalog retrieval and no acceptance labels were used:

```text
code-diver.yml
pyproject.toml
scripts/serve_reranker.sh
src/code_diver/providers/sentence_transformers_embedding_provider.py
src/code_diver/answering/answer_candidate_cross_encoder_reranker.py
src/code_diver/runtime/embedding_runtime_manager.py
src/code_diver/reranking/rerank_score.py
src/code_diver/reranking/llama_cpp_rerank_provider.py
src/code_diver/strategies/cross_encoder_rerank_retrieval_strategy.py
src/code_diver/providers/openai_compatible_embedding_provider.py
src/code_diver/config/embedding_config.py
src/code_diver/config/cross_encoder_rerank_config.py
src/code_diver/runtime/runtime_config.py
src/code_diver/providers/embedding_provider_builder.py
src/code_diver/reranking/rerank_provider_factory.py
src/code_diver/reranking/cross_encoder_document_builder.py
src/code_diver/config/config_loader.py
src/code_diver/settings/defaults.py
src/code_diver/store/json_vector_store.py
src/code_diver/store/qdrant_vector_store.py
docs/qwen3-cross-encoder-rerank-2026-06-02.md
docs/llama-cpp-rerank-runtime-notes-2026-06-02.md
docs/research/2026-09-06_parallel-benchmark.md
docs/research/2026-09-05_ce-capacity-repair.md
docs/research/2026-09-05_ce-evidence.md
docs/research/2026-09-05_latency-independence.md
README.md
CHANGELOG.md
src/code_diver/answering/answer_candidate_reranker.py
src/code_diver/answering/answer_candidate_reranker_factory.py
src/code_diver/strategies/hybrid_candidate_score.py
src/code_diver/strategies/hybrid_candidate_scorer.py
src/code_diver/services/candidate_file_scanner.py
src/code_diver/services/identifier_alias_candidate.py
```

Query:

```text
where are reranking provider configuration, cross-encoder document construction, and runtime Metal serving behavior implemented?
```

For each file and each content cap, the corrected payload represented a document as the exact string:

```text
path: {relative_path}
title: {basename}
content: {file_text[:content_cap]}
```

The two frozen caps were `850` and `2400` characters. Tokenization was checked through the isolated endpoint rather than inferred from character count: at `850`, `34` documents had `155/329/482` minimum/median/maximum tokens and `11162` total; at `2400`, they had `155/663/987` and `22350` total. No document exceeded `2048` tokens.

## Hash distinction

The earlier handoff hashes are retracted. They do not match the files or the corrected canonical payloads.

`payloads_v2.json` itself has file SHA-256:

```text
faa2ebe03efafb652705ae30268057fa5f75b98c3117fe2e587e391a06748ed9
```

The embedded `payload_sha256` is calculated over only `{"query": ..., "documents": ...}` using `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(',', ':'))`; it excludes the outer `content_cap` and `payload_sha256` metadata. The exact values are:

| Cap | Canonical query/documents bytes | Canonical payload SHA-256 | Actual HTTP body bytes | Actual HTTP body SHA-256 |
|---:|---:|---|---:|---|
| 850 | 31,946 | `f20cee9121bf29c960e07b4317a084ccba4a9967f61ee3676ee16a5b18f2ffdb` | 32,026 | `31ec2a833ea459451e09d4a08672054b58921e5e0c44ecdc63a3ebbf81ecf9dc` |
| 2400 | 76,604 | `264139e9b33cec14508fe53a6e03dd66eccefdd1201959d3c861fb4addf75dd8` | 76,684 | `26955d85bb485d8078c9ef8552ea0163787658243bcbca07711216df0d12c2e6` |

The actual request-body hash is distinct because the benchmark sent a copy of the complete frozen entry, appended `model=Qwen3-Reranker-0.6B-Q4_K_M.gguf`, and serialized it with `json.dumps(body, ensure_ascii=False).encode()`. These hashes cover JSON body bytes only, not HTTP headers. The full pretty-printed payload file hash is a third, separate value.

## Request accounting and failed first attempt

The corrected `raw_results_v2.json` contains exactly `20` rows: `8` warm-ups (`2` per profile) and `12` timed requests (`3` per profile). There were `0` errors. Every timed request returned `34` results and `34` finite scores.

The first saved attempt is preserved as `raw_results.json`, `payloads.json`, and `summary.json`. It also contains `8` warm-ups and `12` timed requests, but all `20` requests failed with HTTP 400 because documents were sent as JSON objects instead of the provider-compatible strings. Those failures are not mixed into the corrected metrics.

The corrected profile order was one seeded block shuffle (`Random(42)`), followed by two warm-ups and three timed requests for each block:

```text
baseline_18081 / 2400
explicit_metal_18082 / 850
explicit_metal_18082 / 2400
baseline_18081 / 850
```

This was not a counterbalanced randomized paired-trial design. Backend comparisons below are descriptive joins of the three timed rows for each profile, not proof of causality.

## Corrected timing results

Wall-clock seconds, three timed requests per profile; `p95` is the nearest-rank value for this tiny sample.

| Endpoint/profile | Cap | Failures | Results / finite scores | Median | Range | p95 |
|---|---:|---:|---|---:|---:|---:|
| baseline `18081` | 850 | 0/3 | 34/34 for each request | 2.366504 | 2.297922–2.868729 | 2.868729 |
| explicit Metal `18082` | 850 | 0/3 | 34/34 for each request | 1.986789 | 1.961788–1.991757 | 1.991757 |
| baseline `18081` | 2400 | 0/3 | 34/34 for each request | 3.741956 | 3.639897–3.777357 | 3.777357 |
| explicit Metal `18082` | 2400 | 0/3 | 34/34 for each request | 4.033770 | 4.022513–4.114639 | 4.114639 |

At `850`, the isolated profile was descriptively about `16.1%` faster by median; at `2400`, it was about `7.8%` slower. Because the isolated profile also changed `total_slots` from `4` to `1`, these numbers must not be reported as a Metal or GPU speedup.

## Score and ranking comparison

For each cap, all three descriptive timed joins had `34` common indices, top-10 intersection `10`, identical top-10 order, and no changed top-10 positions:

| Cap | Max absolute score delta | Mean absolute score delta | Median absolute score delta | Top-10 agreement |
|---:|---:|---:|---:|---|
| 850 | 0.0005682558 | 0.0000790426 | 0.0000263662 | 10/10, unchanged |
| 2400 | 0.0009218752 | 0.0001088593 | 0.0000012990 | 10/10, unchanged |

These are score/ranking observations for the same GGUF under two llama-server profiles. They are not MLX results and do not establish MLX parity or superiority. The current `.venv` had no `mlx` or `mlx_lm` package, and no MLX server was installed or benchmarked.

## Artifacts and decision boundary

Copied, byte-for-byte verified JSON evidence is under:

```text
artifacts/research/2026-09-08_metal-runtime/
```

It contains the failed first-attempt trio, corrected `v2` payload/raw/summary files, and `token_counts_v2.json`. The durable originals remain under `/Users/iurii.medvedev/.junie/shared/subagent-artifacts/metal-runtime-2026-09-08/`.

The experiment supports only this conclusion: the explicit `MTL0` llama-server profile served the same model successfully and produced nearly identical rankings on this tiny fixed sample. It does not isolate GPU utilization, does not compare MLX, and does not justify a source integration change. Any MLX coding/integration decision still requires separate approval and a benchmark with an actually installed MLX runtime.