# MLX versus llama.cpp rerank runtime benchmark — 2026-09-08

## Scope and verdict

This is a direct runtime microbenchmark, not an application integration and not a
quality acceptance test. It compares the cached MLX conversion
`mlx-community/Qwen3-Reranker-0.6B-4bit` with the already-running live
llama.cpp endpoint `http://127.0.0.1:18081/v1/rerank` on the same 34 documents,
query, and content caps from `artifacts/research/2026-09-08_metal-runtime/payloads_v2.json`.

- MLX model loading happened once, outside all timing intervals.
- MLX used no HTTP server, project adapter, scorer source file, or application edit.
- MLX calls were strictly sequential with `batch_size=1`; every document was
  tokenized, forwarded, scored, `mx.eval`'ed, and `mx.synchronize`'d independently.
- Each backend/cap pair had two warmups and three timed repetitions.
- Condition order was shuffled with `random.Random(42)` for every repetition cycle.
- All 20 calls completed with zero errors and all 34 scores per backend/cap were
  finite probabilities.

MLX was slower in this sequential batch-1 workload, with high run-to-run
variability. The timing result is the requested runtime evidence; it must not be
interpreted as a quality win or loss because the MLX 4-bit conversion and the
llama.cpp GGUF `Q4_K_M` file are different quantization artifacts.

## Exact invocation and inputs

The benchmark was executed as one finite inline invocation; the Python body was
not materialized as a source/scorer/adapter file. The exact outer invocation
used was:

```sh
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" \
  .tmp/mlx-runtime/bin/python - <<'PY'
import hashlib
import importlib.metadata
import json
import platform
import random
import sys
import time
import urllib.request
from pathlib import Path

import mlx.core as mx
from mlx_lm import load

root = Path.cwd()
out_path = root / "artifacts/research/2026-09-08_mlx-benchmark/benchmark_raw.json"
payload_path = root / "artifacts/research/2026-09-08_metal-runtime/payloads_v2.json"
payloads = json.loads(payload_path.read_text())
assert all(len(payloads[str(cap)]["documents"]) == 34 for cap in (850, 2400))
model_id = "mlx-community/Qwen3-Reranker-0.6B-4bit"
model_revision = "5f324548f1d20c2b5a450f126fc6ef2fb1126524"
model, tok, config = load(model_id, lazy=False, return_config=True)
hf = getattr(tok, "_tokenizer", tok)
instruct = "Given a web search query, retrieve relevant passages that answer the query"
prefix = ("<|im_start|>system\nJudge whether the Document meets the requirements "
          "based on the Query and the Instruct provided. Note that the answer can "
          "only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
true_id = int(hf.convert_tokens_to_ids("yes"))
false_id = int(hf.convert_tokens_to_ids("no"))
pre = hf.encode(prefix, add_special_tokens=False)
suf = hf.encode(suffix, add_special_tokens=False)

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

snapshot = root / f".tmp/mlx-model-cache/huggingface/models--mlx-community--Qwen3-Reranker-0.6B-4bit/snapshots/{model_revision}"
model_hashes = {}
if snapshot.is_dir():
    for path in sorted(snapshot.rglob("*")):
        if path.is_file():
            model_hashes[str(path.relative_to(snapshot))] = sha256_file(path)

def mlx_score(query, doc, index):
    started = time.perf_counter()
    try:
        content = f"<Instruct>: {instruct}\n<Query>: {query}\n<Document>: {doc}"
        content_ids = hf.encode(content, add_special_tokens=False)
        ids = pre + content_ids + suf
        inputs = mx.array([ids], dtype=mx.int32)
        logits = model(inputs)[:, -1, :]
        pair = mx.stack([logits[0, false_id], logits[0, true_id]])
        probs = mx.exp(pair - mx.logsumexp(pair))
        mx.eval(logits, probs)
        mx.synchronize()
        return {"index": index, "error": None,
                "score_yes": float(probs[1].item()),
                "score_no": float(probs[0].item()),
                "token_count": len(ids),
                "content_token_count": len(content_ids),
                "token_ids_head": [int(x) for x in ids[:12]],
                "token_ids_tail": [int(x) for x in ids[-12:]],
                "wall_seconds": time.perf_counter() - started}
    except Exception as exc:
        return {"index": index, "error": f"{type(exc).__name__}: {exc}",
                "wall_seconds": time.perf_counter() - started}

def http_score(query, docs):
    body = json.dumps({"model": "Qwen3-Reranker-0.6B-Q4_K_M.gguf",
                       "query": query, "documents": docs,
                       "top_n": len(docs)}).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:18081/v1/rerank", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            raw, status = response.read(), response.status
        parsed = json.loads(raw)
        return {"error": None, "http_status": status,
                "wall_seconds": time.perf_counter() - started,
                "response": parsed,
                "scores_by_index": {str(int(x["index"])): float(x["relevance_score"])
                                     for x in parsed.get("results", [])}}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}",
                "wall_seconds": time.perf_counter() - started}

def save(record):
    out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

record = {"kind": "runtime_benchmark_raw", "timestamp_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
          "command_description": "Inline MLX official Qwen3 reranker scoring versus live llama.cpp HTTP; no MLX HTTP server",
          "payload_path": str(payload_path), "payloads": {}, "mlx": {}, "llama_cpp": {},
          "protocol": {"warmups_per_backend_cap": 2, "timed_repetitions_per_backend_cap": 3,
                        "random_seed": 42, "backend_calls": "sequential only; no concurrent GPU calls"},
          "schedule": [], "runs": []}
record["payloads"] = {str(cap): {"content_cap": payloads[str(cap)]["content_cap"],
    "payload_sha256_declared": payloads[str(cap)]["payload_sha256"],
    "document_count": len(payloads[str(cap)]["documents"]), "query": payloads[str(cap)]["query"],
    "document_sha256": [hashlib.sha256(d.encode()).hexdigest() for d in payloads[str(cap)]["documents"]]}
    for cap in (850, 2400)}
record["mlx"] = {"model_id": model_id, "model_revision": model_revision,
    "model_hashes": model_hashes, "config_model_type": config.get("model_type"),
    "versions": {n: importlib.metadata.version(n) for n in ("mlx", "mlx-lm", "transformers", "tokenizers")},
    "python": sys.version, "platform": platform.platform(), "device": str(mx.default_device()),
    "metal_available": bool(mx.metal.is_available()), "official_recipe": {"instruct": instruct,
    "prefix": prefix, "suffix": suffix, "true_token": "yes", "false_token": "no",
    "true_id": true_id, "false_id": false_id, "prefix_token_count": len(pre),
    "suffix_token_count": len(suf), "scoring": "softmax([logit(no), logit(yes)])[1] at final prompt position"},
    "batch_policy": "sequential batch_size=1; mx.eval and mx.synchronize after each forward/score"}
record["llama_cpp"] = {"url": "http://127.0.0.1:18081/v1/rerank",
    "model": "Qwen3-Reranker-0.6B-Q4_K_M.gguf",
    "template": "server-internal Qwen3 reranker template is opaque to HTTP client",
    "quantization": "GGUF Q4_K_M; differs from MLX 4-bit conversion"}

rng = random.Random(42)
conditions = [(backend, cap) for cap in (850, 2400) for backend in ("mlx", "http")]
for phase, repeats in (("warmup", 2), ("timed", 3)):
    for repeat in range(repeats):
        cycle = conditions[:]
        rng.shuffle(cycle)
        record["schedule"].append({"phase": phase, "repeat": repeat + 1,
            "order": [{"backend": b, "cap": c} for b, c in cycle]})
        for backend, cap in cycle:
            started = time.perf_counter()
            payload = payloads[str(cap)]
            if backend == "mlx":
                rows = [mlx_score(payload["query"], doc, i) for i, doc in enumerate(payload["documents"])]
                run = {"phase": phase, "repeat": repeat + 1, "backend": backend, "cap": cap,
                       "payload_sha256": payload["payload_sha256"], "document_count": len(rows),
                       "wall_seconds_total": time.perf_counter() - started,
                       "error_count": sum(row.get("error") is not None for row in rows), "rows": rows}
            else:
                result = http_score(payload["query"], payload["documents"])
                run = {"phase": phase, "repeat": repeat + 1, "backend": backend, "cap": cap,
                       "payload_sha256": payload["payload_sha256"], "document_count": len(payload["documents"]),
                       "wall_seconds_total": result["wall_seconds"],
                       "error_count": 1 if result.get("error") else 0, **result}
            record["runs"].append(run)
            save(record)
            print(json.dumps({"phase": phase, "repeat": repeat + 1, "backend": backend,
                              "cap": cap, "wall_seconds": run["wall_seconds_total"],
                              "errors": run["error_count"]}), flush=True)
print(json.dumps({"out": str(out_path), "run_count": len(record["runs"])}, indent=2))
PY
```

The body read only `payloads_v2.json`, loaded the existing cached model, called
the live HTTP endpoint for the llama.cpp baseline, and wrote the raw JSON under
the benchmark artifact directory. The reduced checks are in `summary.json`.

The invocation above is a retained runnable transcription of the executed inline
workload; the raw JSON additionally preserves the actual schedule, metadata,
hashes, and every result from the run.

Declared payload hashes and document counts:

| Cap | Documents | Declared payload SHA-256 | MLX token sum | HTTP usage `prompt_tokens` |
|---:|---:|---|---:|---:|
| 850 | 34 | `f20cee9121bf29c960e07b4317a084ccba4a9967f61ee3676ee16a5b18f2ffdb` | 11,162 | 11,162 |
| 2400 | 34 | `264139e9b33cec14508fe53a6e03dd66eccefdd1201959d3c861fb4addf75dd8` | 22,350 | 22,350 |

MLX token counts are per-document prompt counts. At cap `850`, the range was
155–482 tokens with mean `328.294`; at cap `2400`, the range was 155–987 with
mean `657.353`. The HTTP server reported the corresponding aggregate usage in
each raw response but does not expose per-document token counts.

## Official Qwen3 scoring recipe

The model-card recipe from
`https://huggingface.co/mlx-community/Qwen3-Reranker-0.6B-4bit` was used
literally:

```text
INSTRUCT = Given a web search query, retrieve relevant passages that answer the query
PREFIX = <|im_start|>system
         Judge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>
         <|im_start|>user
SUFFIX = <|im_end|>
         <|im_start|>assistant
         <think>

         </think>

content = <Instruct>: {INSTRUCT}
           <Query>: {query}
           <Document>: {document}
ids = prefix_ids + content_ids + suffix_ids
score = softmax([logit("no"), logit("yes")])[1] at the final prompt position
```

Observed tokenizer IDs were `yes=9693` and `no=2152`; prefix and suffix lengths
were 39 and 9 tokens. The MLX tokenizer has a chat template, but the manual
model-card prompt above was used instead of relying on it. The cached tokenizer
template has the same Qwen3 system/user/assistant structure and the
`<Instruct>`, `<Query>`, and `<Document>` fields.

The llama.cpp `/v1/rerank` implementation owns its internal reranker prompt.
The HTTP client cannot inspect the exact rendered prompt; the live server's
generic chat template was observed through `/props`, but `/v1/rerank` template
handling remains opaque. This is recorded as a template caveat rather than
claiming byte-identical prompts.

Consequently, the exact baseline prompt was not verified by rendering or
tokenizing the server-side `/v1/rerank` template. Only the MLX model-card prompt
was constructed and tokenized directly; any MLX-versus-baseline prompt mismatch
is unknown, not ruled out.

## Runtime versions and model identity

MLX runtime evidence:

| Component | Value |
|---|---|
| Python | CPython 3.12.12, native arm64 |
| `mlx` | 0.32.2 |
| `mlx-lm` | 0.31.3 |
| `transformers` | 5.16.1 |
| `tokenizers` | 0.23.2 |
| Device | `Device(gpu, 0)` |
| Metal available | `true` |
| MLX revision | `5f324548f1d20c2b5a450f126fc6ef2fb1126524` |

MLX snapshot SHA-256 values are preserved in both raw JSON artifacts. The main
weight hash is `model.safetensors` =
`1d212560a5b1c36186787fdae19f11f20fecfc29bef91522e12a8e0d118f4545`.
The llama.cpp server reported:

- model: `Qwen3-Reranker-0.6B-Q4_K_M.gguf`
- path: `.code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf`
- format: GGUF, quantization: `Q4_K_M`
- `n_vocab=151669`, `n_ctx=40960`, `n_embd=1024`, `n_params=595778560`
- reported model size: `390530152` bytes
- `/v1/models` returned no GGUF digest, so no GGUF SHA-256 is claimed here.

## Wall-time results

Times below are aggregate wall time for all 34 documents in one condition. MLX
time includes CPU tokenization, forward, two-class score construction, and the
synchronized GPU completion. HTTP time includes the `urllib` request/response
wall time for one 34-document request; its JSON body was constructed before the
timer.

| Cap | Backend | Timed repetitions (seconds) | Mean | Median | Min–max |
|---:|---|---|---:|---:|---:|
| 850 | MLX | 42.617924, 23.001591, 2.661825 | 22.760447 | 23.001591 | 2.661825–42.617924 |
| 850 | llama.cpp HTTP | 2.007128, 6.265126, 2.037769 | 3.436674 | 2.037769 | 2.007128–6.265126 |
| 2400 | MLX | 101.046208, 91.134174, 11.559149 | 67.913177 | 91.134174 | 11.559149–101.046208 |
| 2400 | llama.cpp HTTP | 5.363247, 4.468724, 4.419027 | 4.750333 | 4.468724 | 4.419027–5.363247 |

The fast final MLX repetition does not replace the slower measurements; all raw
repetitions are retained. The backend/cap pairing and seed-42 execution order are
in `benchmark_raw.json`.

## Schedule and interpretation of the timing anomaly

The two warmup cycles completed before the timed phase began, so every
backend/cap condition had two completed warmup calls before any timed call. They
were not re-run immediately before each individual timed repetition. The actual
cycle orders were:

| Phase | Cycle 1 | Cycle 2 | Cycle 3 |
|---|---|---|---|
| Warmup | MLX2400, HTTP850, HTTP2400, MLX850 | HTTP2400, MLX2400, MLX850, HTTP850 | — |
| Timed | HTTP850, HTTP2400, MLX2400, MLX850 | HTTP850, MLX2400, MLX850, HTTP2400 | HTTP850, MLX2400, HTTP2400, MLX850 |

For MLX the observed timed sequences were `42.617924 → 23.001591 → 2.661825`
seconds at cap `850`, and `101.046208 → 91.134174 → 11.559149` at cap `2400`.
This proves variability and a late fast repetition, not its cause. The retained
evidence has no per-run memory telemetry, allocator trace, or compilation trace;
the setup memory measurement covered only an isolated matrix multiplication.
Therefore memory pressure or compilation cannot be claimed as the explanation.

The forward call was `model(inputs)[:, -1, :]`. The recorded smoke output shape
was `(1, sequence_length, 151669)`, so the model call materialized logits for
all token positions before Python selected the last one for scoring. Model
weights/runtime state persist between documents; per-document `inputs`, logits,
and score arrays are rebound, and no explicit KV/cache object is passed between
documents. MLX allocator reuse, if any, was not measured.

## Score and ranking comparison

Indices are the original zero-based document indices in `payloads_v2.json`.
Scores below use timed repetition 1; repeated scores were identical per backend
and cap (`max_abs_delta=0` across timed repetitions).

| Cap | Cardinality MLX/HTTP | Finite MLX/HTTP | Top-10 overlap | Common top-10 order | Kendall inversions among common top-10 |
|---:|---:|---:|---:|---|---:|
| 850 | 34 / 34 | 34 / 34 | 9 / 10 | different | 19 |
| 2400 | 34 / 34 | 34 / 34 | 9 / 10 | different | 12 |

Top-10 indices:

- Cap `850`, MLX: `[2, 4, 7, 8, 11, 12, 14, 15, 28, 29]`
- Cap `850`, HTTP: `[14, 11, 29, 8, 12, 4, 15, 7, 28, 21]`
- Cap `2400`, MLX: `[4, 8, 11, 12, 14, 15, 21, 29, 2, 7]`
- Cap `2400`, HTTP: `[14, 29, 4, 11, 8, 12, 15, 7, 21, 20]`

Absolute score deltas and threshold checks (`threshold=0.3`):

| Cap | Mean abs delta | Median abs delta | Max abs delta | `abs(delta) >= 0.3` | Threshold flips |
|---:|---:|---:|---:|---|---|
| 850 | 0.070714 | 0.007999 | 0.793683 | indices 5, 13 (2) | indices 5, 13 (2) |
| 2400 | 0.077315 | 0.020820 | 0.694721 | indices 5, 10, 13, 23 (4) | indices 5, 10, 13 (3) |

The exceptional score pairs are:

- Cap `850`: index 5 MLX `0.173828125` vs HTTP `0.949744284`; index 13 MLX
  `0.030151367` vs HTTP `0.823834181`.
- Cap `2400`: index 5 MLX `0.251953125` vs HTTP `0.946674407`; index 10 MLX
  `0.135742188` vs HTTP `0.508434951`; index 13 MLX `0.011840820` vs HTTP
  `0.387686253`; index 23 MLX `0.777343750` vs HTTP `0.469140202`.

These differences are valid observations of two different quantized/runtime
paths and opaque server prompt handling, not a promotion criterion.

## Artifacts and non-changes

- `artifacts/research/2026-09-08_mlx-benchmark/smoke.json`: two-document smoke,
  token IDs, prompt details, hashes, finite scores, and live HTTP response.
- `artifacts/research/2026-09-08_mlx-benchmark/benchmark_raw.json`: all 20 raw
  warmup/timed runs, per-document MLX timings/scores/errors/token IDs, raw HTTP
  responses, payload hashes, model hashes, versions, and randomized schedule.
- `artifacts/research/2026-09-08_mlx-benchmark/summary.json`: derived timing,
  finite/cardinality, ranking-overlap, score-delta, and threshold-flip checks.

No installation, build, source edit, root configuration edit, service restart,
`HOME` change, MLX HTTP server, scorer, or adapter was created.