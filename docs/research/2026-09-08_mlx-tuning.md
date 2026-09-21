# MLX runtime tuning — 2026-09-08

## Result

This was a measurement-only MLX tuning study on the native M3 Max runtime. The
best measured scorer was the existing packaged Qwen3 backbone call followed by
the final-token hidden-state projection through the existing tied embedding
head:

```python
hidden = model.model(inputs)
logits = model.model.embed_tokens.as_linear(hidden[:, -1:, :])
```

It avoids materializing vocabulary logits for every input position while using
no custom layer, kernel, monkeypatch, adapter, or source implementation.

The cap-specific best measured settings were:

| Workload | Best measured configuration | p50 full wall | Full-wall range | Speedup vs sequential MLX |
|---|---|---:|---:|---:|
| cap `850` | final hidden + `2 GiB` MLX free-cache limit | `1.976 s` | `1.515–2.431 s` | `29.4%` |
| cap `2400` | final hidden + `1 GiB` MLX free-cache limit | `4.052 s` | `2.937–4.883 s` | `27.4%` |

The setting is cap-dependent, not a claim of a global optimum. If one setting
must be selected for both caps, `1 GiB` had the lower combined cap p50 in this
sample, while `2 GiB` won cap `850` and `1 GiB` won cap `2400`. No production
switch was made.

## Scope and identity

- Model: `mlx-community/Qwen3-Reranker-0.6B-4bit`.
- Pinned snapshot: `5f324548f1d20c2b5a450f126fc6ef2fb1126524`.
- Main weight hash was retained by the earlier benchmark; no model files were
  changed.
- Runtime: `mlx` `0.32.2`, `mlx-lm` `0.31.3`, Python `3.12.12`, native arm64.
- Device: `Device(gpu, 0)`; Metal available.
- Inputs: both 34-document payloads from
  `artifacts/research/2026-09-08_metal-runtime/payloads_v2.json`, with no
  truncation or document removal.
- Live comparison: `http://127.0.0.1:18081/v1/rerank`; `localhost` was not
  used.
- Model load was outside timing: `0.438 s` in the confirmation run.
- All GPU calls were serial; no service was restarted and no other process was
  modified.

The MLX prompt was constructed and tokenized directly using the model-card
recipe, with `yes=9693`, `no=2152`, prefix length `39`, and suffix length `9`.
The exact server-side prompt used by the llama `/v1/rerank` implementation was
not verified by the HTTP client and remains an explicit caveat.

## Reusable packaged-API invocation

This is the essential finite inline invocation used for the optimized path; it
does not create a source script or application adapter:

```sh
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" \
  .tmp/mlx-runtime/bin/python - <<'PY'
import mlx.core as mx
from mlx_lm import load

model, tokenizer, config = load(
    "mlx-community/Qwen3-Reranker-0.6B-4bit",
    revision="5f324548f1d20c2b5a450f126fc6ef2fb1126524",
    lazy=False,
    return_config=True,
)
# Recommended cap-850 profile. Use 1 * 1024**3 for cap 2400.
mx.set_cache_limit(2 * 1024**3)
mx.clear_cache()
hf = getattr(tokenizer, "_tokenizer", tokenizer)
instruct = "Given a web search query, retrieve relevant passages that answer the query"
prefix = ("<|im_start|>system\nJudge whether the Document meets the requirements "
          "based on the Query and the Instruct provided. Note that the answer "
          "can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
query = "example query"
document = "example document"
yes_id = int(hf.convert_tokens_to_ids("yes"))
no_id = int(hf.convert_tokens_to_ids("no"))
prompt_token_ids = (
    hf.encode(prefix, add_special_tokens=False)
    + hf.encode(
        f"<Instruct>: {instruct}\n<Query>: {query}\n<Document>: {document}",
        add_special_tokens=False,
    )
    + hf.encode(suffix, add_special_tokens=False)
)
inputs = mx.array([prompt_token_ids], dtype=mx.int32)
hidden = model.model(inputs)
last_logits = model.model.embed_tokens.as_linear(hidden[:, -1:, :])
pair = mx.stack([last_logits[0, 0, no_id], last_logits[0, 0, yes_id]])
probabilities = mx.softmax(pair.astype(mx.float32))
mx.eval(hidden, last_logits, probabilities)
mx.synchronize()
print(float(probabilities[1].item()))
PY
```

This finite documented invocation runs the optimized scorer with the recommended
cap-850 cache profile (`2 GiB`); use `1 * 1024**3` for cap `2400`. It prints one
score only and does not write or overwrite any raw artifact. The historical full
workload's incremental results remain in
`artifacts/research/2026-09-08_mlx-tuning/tuning_raw.json`.

## Experimental design

The study used two warmups and five timed repetitions per cap/configuration,
with all conditions shuffled using `random.Random(42)`. The confirmation set
was:

- sequential MLX reference: `model(inputs)[:, -1, :]` with a `2 GiB` free-cache
  limit;
- optimized final-hidden path with `1 GiB` free-cache limit;
- optimized final-hidden path with `2 GiB` free-cache limit;
- live llama HTTP request at the fixed loopback address.

Every condition was persisted after completion. A per-condition `180 s`
timeout retained failures as raw records rather than retrying them indefinitely;
none of the confirmation conditions timed out or errored.

The timing fields are deliberately separated:

| Configuration | Cap | Full wall p50 / range | Synchronized GPU p50 / range | Tokenization p50 / range |
|---|---:|---|---|---|
| sequential MLX | 850 | `2.799 / 2.119–3.368 s` | `2.645 / 2.041–2.957 s` | `0.0301 / 0.0159–0.0730 s` |
| hidden + `1 GiB` | 850 | `2.078 / 1.616–2.551 s` | `2.003 / 1.524–2.302 s` | `0.00170 / 0.00127–0.00400 s` |
| hidden + `2 GiB` | 850 | `1.976 / 1.515–2.431 s` | `1.901 / 1.448–2.221 s` | `0.00223 / 0.00113–0.00370 s` |
| llama HTTP | 850 | `3.194 / 2.128–3.440 s` | not exposed | server-side |
| sequential MLX | 2400 | `5.578 / 3.942–6.394 s` | `5.244 / 3.829–5.886 s` | `0.0978 / 0.0270–0.140 s` |
| hidden + `1 GiB` | 2400 | `4.052 / 2.937–4.883 s` | `3.858 / 2.867–4.565 s` | `0.00205 / 0.00093–0.00279 s` |
| hidden + `2 GiB` | 2400 | `4.238 / 3.152–5.128 s` | `3.996 / 3.009–4.606 s` | `0.00187 / 0.00160–0.00335 s` |
| llama HTTP | 2400 | `6.581 / 4.887–7.354 s` | not exposed | server-side |

The earlier high-variance batch-1 measurements are not replaced or discarded;
the new randomized paired run is additional evidence under the stated cache
and hidden-output configurations.

## Allocator cache screening

The measured cap-`850` hidden-final screening used the existing MLX allocator
cache API only. It did not change wired limits or purge the system cache:

| Free-cache limit | Two screening full-wall results |
|---:|---:|
| `0` | `1.261 s`, `1.250 s` |
| `512 MiB` | `1.254 s`, `1.254 s` |
| `1 GiB` | `1.252 s`, `1.246 s` |
| `2 GiB` | `1.235 s`, `1.235 s` |

The cap-`2400` choice was resolved by the five-repetition confirmation rather
than extrapolated from cap `850`.

## Correctness and numerical evidence

Against the same-weight sequential MLX reference, each optimized candidate had
34/34 common finite scores:

| Cap | Candidate | Max absolute score difference | Mean absolute difference | Top-10 agreement | `0.3` threshold flips | Same-boundary ratio |
|---:|---|---:|---:|---:|---:|---:|
| 850 | hidden + `1 GiB` or `2 GiB` | `0.003628` | `0.000318` | `10/10` | `0` | `34/34` |
| 2400 | hidden + `1 GiB` or `2 GiB` | `0.012109` | `0.000861` | `10/10` | `0` | `34/34` |

The two cache settings do not change the score result in the retained
measurements. The final top-10 was explicitly sorted by descending score and
index as a tie breaker. For cap `850`, the ordered indices were
`14,29,11,4,8,12,7,15,2,28`; for cap `2400`, they were
`14,8,4,29,11,15,12,21,27,7`. The index sequences are not numerically sorted,
while the score sequences are descending, so the prior index-order concern is
not perpetuated.

The score calculation used a float32 two-logit softmax over bfloat16 logits.
For comparison, bfloat16 softmax was also retained separately: for each MLX
timed configuration (340 rows), every correction was nonzero, the median
absolute `yes`-probability correction was approximately `0.00016`–`0.00019`,
and the maximum was `0.0037545`. This is a numerical correction record, not a
speed or quality acceptance claim.

Against the live llama endpoint, the hidden candidates had `9/10` top-10
intersection at both caps. Threshold flips were `2/34` at cap `850` and
`3/34` at cap `2400`; maximum score deltas were approximately `0.793` and
`0.690`. The MLX conversion and llama GGUF `Q4_K_M` weights differ, and the
llama prompt is opaque through this API, so these comparisons are not quality
parity acceptance.

## Batching and padding result

The installed Qwen3 packaged model creates its causal attention mask from
sequence shape and exposes no external attention-mask or position-id argument.
The unequal-length smoke probe used two actual documents (`401` and `334`
tokens) padded to a `2 x 401` array. One document's score changed by
`0.020872`, so naive padding is invalid.

Consequently, batch sizes `2`, `4`, `8`, `16`, and `34` were rejected before
timing for this unequal-length workload; batch size `1` is the only validated
configuration. Length bucketing was not invented around the missing mask API,
and no custom padding, position, attention, or kernel implementation was
written. The rejection is recorded in `screening_raw.json` and
`smoke.json`.

## Memory and system state

The best candidate memory telemetry, measured after each timed condition, was:

| Candidate | Cap | Active p50 / descriptive p95 | Cache p50 / descriptive p95 | Peak p50 / descriptive p95 |
|---|---:|---:|---:|---:|
| hidden + `2 GiB` | 850 | `335,249,426 / 335,249,426` B | `2,146,710,654 / 2,147,195,624` B | `865,337,600 / 865,337,600` B |
| hidden + `1 GiB` | 2400 | `335,249,416 / 335,249,426` B | `1,071,074,954 / 1,071,209,329` B | `1,338,774,588 / 1,338,774,588` B |

The captured safe system snapshot reported 64 GiB physical memory, 74% free
system memory, and approximately 36.9 GiB of 37.9 GiB swap used. These are
context measurements only; this study does not infer that swap or memory
pressure caused the earlier variance.

## Artifacts and next step

- `artifacts/research/2026-09-08_mlx-tuning/smoke.json`: hidden-path score
  gate, float32 scoring, and invalid padding probe.
- `artifacts/research/2026-09-08_mlx-tuning/screening_raw.json`: full 34-item
  screening, cache settings, memory, and same-weight validity.
- `artifacts/research/2026-09-08_mlx-tuning/tuning_raw.json`: incremental raw
  confirmation runs, randomized schedules, HTTP responses, and derived summary.
- `.plans/2026-09-08_mlx-tuning.md`: bounded experiment plan.
- `.session/2026-09-08_mlx-tuning.md`: session decision and handoff.

The concrete next step, if parent-level integration is later approved, is to
implement the final-hidden path in the owning adapter and rerun an application
level regression with the same 34-document score checks. That implementation
was intentionally not performed in this tuning scope.