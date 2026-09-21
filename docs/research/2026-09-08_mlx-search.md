# MLX reranker integration diagnosis — 2026-09-08

## Decision

The ready-made `vllm-metal` service is semantically usable with the pinned
Qwen3 reranker only when the extracted official tokenizer chat template is
passed explicitly. It is **not promoted**: the available integrated evidence
does not show a faster or more accurate search, the service accumulated
system-wide memory pressure, and the frozen evaluation manifest did not use
direct IPv4 for the Python baseline.

The owned MLX service was stopped after this bounded diagnosis. Existing
`18081`, embedding `8001`, and Qdrant `6333` services were not restarted or
stopped.

## Frozen model, template, and runtime

- Model: `mlx-community/Qwen3-Reranker-0.6B-4bit`
- Local snapshot: `5f324548f1d20c2b5a450f126fc6ef2fb1126524`
- Model config SHA-256: `09adff58b65e9305009c9caa4923b3365b18dd2f84135b44168aaf869278bea4`
- Runtime: arm64 macOS `26.6.2`
- `vllm`: `0.28.0+cpu`
- `vllm-metal`: `0.28.0`
- Serving `mlx`: `0.32.0`
- `mlx-lm`: `0.31.3`
- `transformers`: `5.12.1`
- Official template file: `.tmp/qwen3-reranker-official-chat-template.jinja`
- Template SHA-256: `6f682162495ec5b39fd9005c01b6aa2a74669379fe967039f1e2cbbe8752369d`

The template renders the Qwen3 reranker system instruction, `<Instruct>`,
`<Query>`, `<Document>`, and assistant `<think>...</think>` suffix. A semantic
two-document smoke returned `usage.prompt_tokens=170`, score
`0.9883589744567871` for the Beijing document, and
`0.0000946595537243411` for the Paris document. The earlier generic `28`
token smoke is excluded from quality evidence.

## Actual launch command

This is the command actually used for the official-template endpoint; the
model path has one, not two, `snapshots` components:

```bash
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" \
VLLM_ENABLE_V1_MULTIPROCESSING=0 \
VLLM_METAL_USE_PAGED_ATTENTION=1 \
VLLM_METAL_MEMORY_FRACTION=auto \
.tmp/mlx-search-runtime/bin/vllm serve \
  "$PWD/.tmp/mlx-model-cache/huggingface/models--mlx-community--Qwen3-Reranker-0.6B-4bit/snapshots/5f324548f1d20c2b5a450f126fc6ef2fb1126524" \
  --host 127.0.0.1 --port 18083 \
  --runner pooling --max-model-len 2048 \
  --chat-template "$PWD/.tmp/qwen3-reranker-official-chat-template.jinja" \
  --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}'
```

The endpoint identity was the pinned local snapshot, and the route was
`POST http://127.0.0.1:18083/v1/rerank`. No custom adapter, model source,
package patch, or application source was used.

## Actual integrated evaluation command and manifest caveat

The executed v2 run used this in-memory Rust command override:

```bash
PYTHONPATH=src:scripts \
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" \
.venv/bin/python -c 'import sys; from pathlib import Path; import research_rust_full_eval as m; m.OUT=Path("artifacts/research/2026-09-08_mlx-search"); m.COMMAND=[("http://127.0.0.1:18083/v1/rerank" if x=="http://localhost:18081/v1/rerank" else x) for x in m.COMMAND]; sys.argv=["research_rust_full_eval.py","--run","qwen3-reranker-vllm-metal-official-template-30pairs-v2","--max-pairs","30","--seconds","3600"]; m.main()'
```

The harness preserved retrieval `360`, CE candidate limit `34`, result limit
`10`, serial request behavior, and failure-inclusive quality. Its actual
frozen manifest was:

- Python CE: `http://localhost:18081/v1/rerank`
- Rust MLX CE: `http://127.0.0.1:18083/v1/rerank`
- Embedding: `http://localhost:8001/v1/embeddings`
- Qdrant: `http://localhost:6333`
- Embedding query prefix: `task: code retrieval | query: `
- Embedding document prefix: `title: none | text: `
- Boundary: persistent request wall time excluding both initializations

Therefore this run is not IPv4-clean for the Python baseline. The Python
process likely resolved `localhost` locally, but that is not equivalent to the
requested manifest-level proof of `127.0.0.1`; no claim of such proof is made.

The native command in the manifest did correctly contain only the MLX arm
override while retaining retrieval and CE budgets:

```text
native/code_diver_search_bin/target/release/code_diver_search_bin --server --catalog /tmp/rust_catalog.jsonl --graph /tmp/rust_graph.jsonl --model artifacts/ce_meta_ranker/ce_meta_ranker.lgb.txt --embedding-url http://localhost:8001/v1/embeddings --qdrant-url http://localhost:6333 --ce-url http://127.0.0.1:18083/v1/rerank --retrieval-limit 360 --candidate-limit 34 --limit 10
```

Manifest SHA-256: `703ad906140c42bf0709422f69f44e9a2cd966935e10470218ffa75296408dbe`.

## Integrated evidence retained

Run directory:
`artifacts/research/2026-09-08_mlx-search/qwen3-reranker-vllm-metal-official-template-30pairs-v2/`.

The frozen run contains `62` journal events: `31` begins and `31` results,
covering `16` distinct cases. It contains `15` fully completed Python/MLX
paired cases plus one additional MLX-only failed result at index `30`.
There are no pending journal entries, and index `30` was not retried.

For the `15` matched pairs in the `full1065` prefix:

| Arm | Attempts | Failures | Hit@10 | MRR@10 | p50 request ms | p95 request ms |
|---|---:|---:|---:|---:|---:|---:|
| Python | 15 | 0 | 0.9333333333 | 0.9333333333 | 97144.09 | 107056.66 |
| Rust/MLX, failure-inclusive denominator 16 | 16 | 1 | 0.8125 | 0.6979166667 | 98905.49 | 176770.29 |

Matched-pair deltas over the `15` pairs only were Rust-minus-Python
`hit@10=-0.0666666667` and `MRR=-0.1888888889`. The Rust denominator of `16`
includes the unmatched failure and must not be confused with the paired
delta denominator.

The failed result at index `30` is retained verbatim:

```text
RuntimeError: Native server exited: Error: "CE rerank request failed: error sending request for url (http://127.0.0.1:18083/v1/rerank)"
```

The earlier two-pair smoke is diagnostic only, not acceptance evidence:

- Python: hit@10/MRR `1.0 / 1.0`, p50/p95 `10745.96 / 96911.65 ms`.
- Rust/MLX: hit@10/MRR `1.0 / 0.5833333333333334`, p50/p95
  `50700.57 / 55058.24 ms`.

`WHERE78` was not reached in the interrupted full run. `mech150` and
`mech_file229` each had four paired cases in the retained prefix, with Python
`0.75 / 0.75` and Rust/MLX `0.75 / 0.625` for hit@10/MRR. These prefixes are
also exploratory and do not establish an independent holdout result.

Results journal SHA-256:
`f0012dc11b031f8ac01df276c78d264b25b32e1486ae6e680ea6879f046594a4`.

## Bounded systemic diagnosis

Raw records are in:
`artifacts/research/2026-09-08_mlx-search/bounded-diagnosis-20260908T2300.jsonl`.

All probes were serial, two documents for CE, and had a `30 s` request timeout.

| Probe | Payload/configuration | Result |
|---|---|---|
| Embedding | `127.0.0.1:8001`, model `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`, manifest prefix `task: code retrieval | query: ` | timeout at `30.44 s` |
| Llama CE | `127.0.0.1:18081`, two Beijing/Paris documents | HTTP `200` in `15.30 s`; scores `0.9994862079620361` and `0.0002942678693216294`; `prompt_tokens=170` |
| MLX CE | `127.0.0.1:18083`, official template, same two documents | timeout at `30.00 s` |

The first embedding attempt used an incorrect Qwen3 instruction-style prefix and
also timed out (`30.03 s`); it is retained but is not used as the correct-prefix
result. The manifest-prefix retry is the valid embedding diagnosis and also
timed out.

Before probing, `memory_pressure` reported `67%` free and swap usage
`64327.88 MiB / 65536 MiB`; `vm_stat` showed `9,612,733` pages stored in the
compressor. During the owned server, vLLM logs showed `Running: 1 reqs,
Waiting: 12 reqs` and prompt throughput around `442.7` then `263.3` tokens/s.
After stopping the owned service, free memory rose to `70%`; swap reported
`70702.19 MiB / 73728 MiB`. This is evidence of severe system pressure and
queueing, not proof that `--memory-fraction=auto` or paged attention alone is
the root cause.

The common slowness is therefore not isolated to one model: embedding timed
out, llama needed `15.3 s` even for two documents, and MLX did not complete in
`30 s`. The prior roughly `97 s` end-to-end timings cannot be promoted to a
model comparison while this shared pressure and queued workload are present.

## Resume and promotion rules

`research_rust_full_eval.py` uses a frozen manifest and journal. On resume it
rejects changed identities, converts any `begin` without a result into a
failure with unknown latency, and skips result indices already present. The
existing `--max-pairs` limit counts newly completed pairs in that invocation;
it does not retry completed failures. This is why the failed index `30` was
preserved and not silently replaced.

The next credible configuration test, if desired, is a new run with a newly
frozen manifest that explicitly sets both CE URLs and the embedding/Qdrant URLs
to verified IPv4 loopback addresses, after the machine has no competing GPU or
swap-heavy workload. It must first repeat only bounded one-request diagnostics,
then use the same `360/34/10` budgets; no acceptance claim should be made from
the current run.