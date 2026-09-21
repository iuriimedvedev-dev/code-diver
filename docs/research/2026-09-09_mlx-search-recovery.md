# MLX search recovery — 2026-09-09

## Result

The cached MLX reranker is semantically responsive with an explicit
conservative allocation, but the requested paired evaluator run is blocked by
the existing embedding runtime-management guard. No application source,
adapter, package, model, template, unrelated service, or non-owned process was
changed. The owned `18083` server was stopped after the bounded smoke.

The paired `frozen2smoke` and 30-distinct-pair evaluation were **not run**:
running them would require bypassing a guard or changing application code, both
outside this task and explicitly disallowed.

## Environment and exact MLX command

- Platform: arm64 macOS `26.6.2`.
- Python: `3.12.12`.
- `vllm`: `0.28.0+cpu`; `vllm-metal`: `0.28.0`; `mlx`: `0.32.0`;
  `mlx-lm`: `0.31.3`; `transformers`: `5.12.1`.
- Model snapshot:
  `mlx-community/Qwen3-Reranker-0.6B-4bit`,
  `5f324548f1d20c2b5a450f126fc6ef2fb1126524`.
- Model `config.json` SHA-256:
  `09adff58b65e9305009c9caa4923b3365b18dd2f84135b44168aaf869278bea4`.
- Official template SHA-256:
  `6f682162495ec5b39fd9005c01b6aa2a74669379fe967039f1e2cbbe8752369d`.

The owned server was launched on IPv4 loopback with the following command:

```bash
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" \
VLLM_ENABLE_V1_MULTIPROCESSING=0 \
VLLM_METAL_USE_PAGED_ATTENTION=1 \
VLLM_METAL_MEMORY_FRACTION=0.35 \
"$PWD/.tmp/mlx-search-runtime/bin/vllm" serve \
  "$PWD/.tmp/mlx-model-cache/huggingface/models--mlx-community--Qwen3-Reranker-0.6B-4bit/snapshots/5f324548f1d20c2b5a450f126fc6ef2fb1126524" \
  --host 127.0.0.1 --port 18083 --runner pooling --max-model-len 2048 \
  --gpu-memory-utilization 0.35 --block-size 16 --max-num-seqs 1 \
  --max-num-batched-tokens 2048 --max-num-scheduled-tokens 2048 \
  --chat-template "$PWD/.tmp/qwen3-reranker-official-chat-template.jinja" \
  --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}'
```

This uses the installed supported controls: numeric Metal memory fraction,
numeric engine GPU utilization, paged attention, one active sequence, block
size `16`, and `2048`-token scheduler ceilings. Readiness succeeded on the
fifth short poll; `/v1/models` reported the pinned snapshot and
`max_model_len=2048`.

## IPv4 health gate

The initial direct IPv4 probes were bounded to 30 seconds per POST and had one
warm follow-up after success:

| Service | Cold | Warm | Result |
|---|---:|---:|---|
| Embedding `127.0.0.1:8001` | `2.197 s` | `0.084 s` | HTTP `200`, model `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`, correct prefix `task: code retrieval \| query: ` |
| Llama CE `127.0.0.1:18081` | `8.951 s` | `0.093 s` | HTTP `200`, two-document semantic result |
| Qdrant `127.0.0.1:6333` | — | — | HTTP `200` on `/collections` |
| MLX CE `127.0.0.1:18083` before launch | — | — | connection refused, as expected after the prior owned shutdown |

After the owned MLX process was stopped, embedding, llama, and Qdrant again
returned HTTP `200`; their service processes were not restarted or stopped.

## MLX bounded semantic smoke

All requests used the official template endpoint and a `120 s` maximum request
time. Raw request and response JSON is retained in
`artifacts/research/2026-09-09_mlx-search-recovery/`.

| Payload | Time | Prompt tokens | Result |
|---|---:|---:|---|
| Two documents, cold | `0.464 s` | `166` | Beijing first, score `0.6775732040405273`; Paris `0.00003331936022732407` |
| Two documents, warm | `0.068 s` | `166` | Beijing first, score `0.6804620027542114`; Paris `0.00003325187572045252` |
| Fixed 34, short | `0.392 s` | `3016` | Relevant document index `0` first, score `0.9985312819480896` |
| Fixed 34, long | `1.307 s` | `11423` | Relevant document index `0` first, score `0.9963328242301941` |

Evidence hashes:

| File | SHA-256 |
|---|---|
| `semantic-2docs.request.json` and warm request | `ca005b7f90b358e31cf3992d4458cd312247804c74ad9b11d2555b8fbf361a31` |
| `semantic-2docs.response.json` | `9160f4717c667aeb2e4f5d76be96cae6bbc43fcf3506d61d8c64e46a1e06da5d` |
| `semantic-2docs-warm.response.json` | `b0cb601c2870216173948c54e5bc1551756c6e1a07b9d25ba5c311dec578b08c` |
| `fixed34-short.request.json` | `4e230e1aec5ff94d5956a16c1b070f6a372ceca4eb81a0b126d2002a62200adb` |
| `fixed34-short.response.json` | `879bcd06f6d7cf1467c14b2205923aa6b636d0c8c27ac2b79f163159e689d2f2` |
| `fixed34-long.request.json` | `dd9a011ed87d8970c98cf9f592a97c6fc5ddd21e4c3846429e09cae1e4563b71` |
| `fixed34-long.response.json` | `3f563797278ae81c65db6649259783d6b8b773905a62053f698888fd24fea8dd` |

## Memory boundary

`memory_pressure -Q` reported free memory of `49%` before the MLX smoke, `20%`
after the short 34-document request, and `20%` after the long request. The
owned server was then stopped; free memory recovered to `56%`. `vm_stat`
pages stored in compressor were respectively `7,871,322`, `7,848,240`,
`7,836,526`, and `7,423,860`. The measurements show a concrete allocation
regression and recovery, not proof of active thrashing from swap occupancy.

## Evaluator and blocker

The existing evaluator tests passed:

```text
Ran 4 tests in 0.001s
OK
```

An in-memory module override (importing `research_rust_full_eval` directly,
not using `runpy`) can truthfully set all routes to IPv4:

- Python CE: `http://127.0.0.1:18081/v1/rerank`
- Rust CE: `http://127.0.0.1:18083/v1/rerank`
- Embedding: `http://127.0.0.1:8001/v1/embeddings`
- Qdrant: `http://127.0.0.1:6333`
- Native budgets: retrieval `360`, candidate `34`, result `10`

But `local_embedding_profile_key(c)` returns `qwen3-0.6b` because the registry
has the exact same provider/model/IPv4 URL tuple. Before provider construction,
the evaluator intentionally raises when that key is non-`None`:

```python
if local_embedding_profile_key(c) is not None:
    raise RuntimeError("Embedding config would invoke runtime management")
```

The supported runtime-management path is `RuntimeConfigStore` plus
`EmbeddingRuntimeManager`; it is not an evaluator route override and invoking
or bypassing it would violate the requested no-management/no-guard-bypass
boundary. Therefore no truthful frozen IPv4 manifest was created and no
paired quality or latency claim is made.

## Reproducibility artifacts

- Plan: `.plans/2026-09-09_mlx-search-recovery.md`
- Evidence: `artifacts/research/2026-09-09_mlx-search-recovery/`
- This report: `docs/research/2026-09-09_mlx-search-recovery.md`
- Session handoff: `.session/2026-09-09_mlx-search-recovery.md`