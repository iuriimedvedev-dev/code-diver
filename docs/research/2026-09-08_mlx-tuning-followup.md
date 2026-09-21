# MLX tuning follow-up — 2026-09-08

## Result

This follow-up was a fresh, measurement-only continuation of the earlier MLX
tuning study. It investigated the installed packaged batching API, screened
candidates against sequential same-token scoring before timing, measured the
packaged quantized head, ran fresh seed-43 timings, and queried the existing
embedding service. No application source, model weights, precision settings,
packages, services, or live configuration were changed.

The best *measured* new profile was exact-length grouping at cap `850`, with a
full-wall p50 of `1.1900 s` across seven timed repetitions. This is not a
promotion recommendation: it groups only four duplicate-length pairs in the
cap-`850` payload and did not win at cap `2400`. The dependable cap-specific
choice therefore remains the earlier optimized final-hidden profile: `2 GiB`
cache for cap `850` and `1 GiB` for cap `2400`. No E2E parity claim is made.

## Identity and boundaries

| Item | Value |
|---|---|
| Model | `mlx-community/Qwen3-Reranker-0.6B-4bit` |
| Snapshot | `5f324548f1d20c2b5a450f126fc6ef2fb1126524` |
| Runtime | `mlx` `0.32.2`, `mlx-lm` `0.31.3`, Python `3.12.12`, native arm64 |
| Device | `Device(gpu, 0)`; Metal available |
| Payload | `artifacts/research/2026-09-08_metal-runtime/payloads_v2.json` |
| Payload SHA-256 | `faa2ebe03efafb652705ae30268057fa5f75b98c3117fe2e587e391a06748ed9` |
| Model manifest SHA-256 | `cf15d99b8465e6ea10fe64163f295eb995b7efe6127944a0259b8439fe061c94` |
| GPU execution | Serial only |
| Services | Existing services only; no restart and no live llama comparison |

The model manifest hash is over the pinned snapshot file names, sizes, and
content hashes. All 34 documents were retained for both caps; no token or
document budget was reduced.

## Batching API investigation

The installed package exposes `BatchKVCache(left_padding: List[int])`. Its
documented contract is left-padded inputs, and the Qwen3 backbone accepts the
cache list through `model.model(inputs, cache=...)`. The cache supplies the
left-padding mask and per-row rotary offsets; the packaged Qwen3 call does not
accept a caller-supplied attention mask or position-id argument.

### Unequal-length `BatchKVCache`

The full 34-document left-padded candidate was executed and compared against a
sequential call for the identical token arrays before any candidate timing:

| Cap | Finite | Max absolute score delta | Mean absolute delta | Sorted top-10 intersection | Exact sorted top-10 list | `0.3` flips | Gate |
|---:|---:|---:|---:|---:|---:|---:|---|
| `850` | `34/34` | `0.0307673` | `0.00357684` | `10/10` | yes | `0` | **rejected / not numerically validated** |
| `2400` | `34/34` | `0.0223849` | `0.00307589` | `10/10` | no | `0` | **rejected / not numerically validated** |

Finite output and stable membership were not sufficient for numerical
equivalence. The probe script applied a `1e-4` max-delta gate, but that numeric
tolerance was not explicitly pre-registered in the plan; therefore this is a
rejected/not-validated gate result, not proof of semantic incorrectness,
impossibility, or a wrong implementation. At cap `2400`, the two top-10 lists
also differed in order despite `10/10` membership intersection. Naive padding
and the packaged offset path were not timed as valid optimizations. The raw
file retains every score and delta.

### Exact-length groups

Ordinary packaged backbone calls on same-length token groups reproduced the
sequential scores with zero observed delta in the correctness probe. The raw
group records retain those per-index score arrays and therefore support exact
score equality for the tested groups. The timing raw retains `10/10` top-10
intersection and zero max delta for every exact-group timed run, but does not
retain a separate candidate top-10 list; no stronger raw-based claim is made.
The payloads contain very few such opportunities:

- cap `850`: four duplicate-length groups, at lengths `307`, `334`, `337`, and
  `375` tokens;
- cap `2400`: one duplicate-length group, at length `734` tokens.

All other documents are singleton groups. This path is correct, but it cannot
turn the workload into a broadly batched workload without introducing
unsupported padding or custom attention code.

## Fresh paired timing

The fresh comparison used two warmups and seven randomized paired timed
repetitions per condition and cap, `random.Random(43)`, serial GPU calls, and
the cap-specific cache profile. Full wall includes tokenization; synchronized
GPU time and tokenization time are reported separately. All `28` timed records
were retained, finite, and error-free.

| Cap | Condition | Full-wall p50 / range | Tokenization p50 / range | GPU p50 / range |
|---:|---|---:|---:|---:|
| `850` | current hidden final-token, `2 GiB` | `1.2168 / 1.1866–1.3202 s` | `0.01135 / 0.01057–0.01474 s` | `1.2047 / 1.1758–1.3055 s` |
| `850` | exact-length groups, `2 GiB` | `1.1900 / 1.1694–1.2555 s` | `0.01105 / 0.01083–0.01329 s` | `1.1790 / 1.1586–1.2422 s` |
| `2400` | current hidden final-token, `1 GiB` | `2.8387 / 2.5595–3.2354 s` | `0.02280 / 0.02189–0.02653 s` | `2.8168 / 2.5337–3.2129 s` |
| `2400` | exact-length groups, `1 GiB` | `2.7946 / 2.5865–3.2486 s` | `0.02183 / 0.02083–0.02753 s` | `2.7732 / 2.5611–3.2272 s` |

Paired full-wall differences for exact grouping versus serial were:

- cap `850`: `6/7` wins, median `-1.575%`, mean `-1.990%`;
- cap `2400`: `3/7` wins, median `+0.407%`, mean `+0.217%`.

The cap-`2400` p50 happened to be slightly lower for grouping, but paired
results did not support a repeatable benefit. The new tokenization measurements
also resolve the earlier boundary concern: tokenization was approximately
`0.011 s` and `0.023 s` at the two caps, while GPU execution dominated full
wall time. These are new seed-43 measurements and are not counted as the old
seed-42 confirmation set.

Correctness during every timed condition was `34/34` finite, zero maximum score
delta for exact groups, `10/10` top-10 intersection, and zero `0.3` threshold
flips against the serial reference.

## Packaged quantized head

The tied head is the packaged `QuantizedEmbedding` with `4` bits, group size
`64`, affine mode, and `as_linear(x)`. It emits the full vocabulary, not a
dedicated selected-token projection:

- full output: shape `[1, 1, 151669]`, dtype `mlx.core.bfloat16`, all finite;
- selected `no/yes` output after the final-token projection: shape `[1, 1, 2]`,
  dtype `mlx.core.bfloat16`, all finite;
- no packaged two-ID-only head API was exposed;
- the packaged wrapper and the direct tied-head path at the same final-token
  boundary produced yes probabilities `0.00192673` and `0.00205074`; the
  selected-logit delta was `0.0625` and probability delta `0.0001240` across
  those independent forward calls.

This probe did not change weights, precision, kernels, or package code. The
existing final-hidden plus `as_linear` path remains the supported way to avoid
materializing logits at every input position; selecting two IDs happens after
the packaged quantized projection.

## Existing embedding endpoint

The probe used explicit `http://127.0.0.1:8001/v1/embeddings`, the current
configured model `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`, and the current
prefix `Represent this code search query for retrieving relevant files: `. The
earlier `52.4723 s` value is retained only as the first observed request in an
already-running service; it is not startup or cold-start evidence, and its
cause is unknown.

A new serial probe used five different real repository queries after `60 s`
without requests from this workload (not evidence that the service was globally
idle). Before embeddings, `/health` returned `200` in `0.01650 s` and
`/v1/models` returned `200` in `0.00126 s`, listing the expected model. These
readiness/model calls do not establish that the embedding model was warmed.
All five embedding requests returned `200`, finite `1024`-dimensional vectors,
and the expected response model:

| Query index | Result | Wall time |
|---:|---|---:|
| `0` | success, finite `1024` dimensions | `2.39728 s` |
| `1` | success, finite `1024` dimensions | `0.01671 s` |
| `2` | success, finite `1024` dimensions | `0.01801 s` |
| `3` | success, finite `1024` dimensions | `0.01809 s` |
| `4` | success, finite `1024` dimensions | `0.01976 s` |

The first post-idle request was `132.8x` the median of the four subsequent
requests (`0.01809 s`). No request error, timeout, non-finite vector, model
mismatch, or concurrent GPU call was observed. This reproduces a first-request
after-workload-idle anomaly, but does not identify whether it came from OS/Metal
residency, runtime behavior, or another cause.

The retained launch command is `scripts/serve_embedder.sh`: it invokes vLLM
pooling with model, loopback host/port, and `--max-model-len`, but no warmup,
idle-unload, keep-alive, or model-residency setting. The installed vLLM help
search exposed cache and kernel warmup configuration sections, not a confirmed
embedding idle-unload control. The repository's concrete operational workaround
is the existing `scripts/keep_services_warm.py` command, which sends a separate
one-token request periodically; it is a latency workaround, not a server
configuration, and was not started or changed here. No production integration
is claimed.

## Raw artifacts and reproducibility

| Artifact | SHA-256 |
|---|---|
| `docs/research/2026-09-08_mlx-tuning-followup/batch_correctness_raw.json` | `6791757ec238e814d3d20757f9329b539861c1fe70a822de6d90b053cb0e57a2` |
| `docs/research/2026-09-08_mlx-tuning-followup/head_and_timing_raw.json` | `37b559660017bbad2d5c0899f90a2e4e89e01004b025cd2f216351a833a402b0` |
| `docs/research/2026-09-08_mlx-tuning-followup/embedding_raw.json` | `5cffa5bc2a93146d0609996b719825e851b540f44927a7845d56c18bf3b17c62` |
| `docs/research/2026-09-08_mlx-tuning-followup/embedding_idle_probe_raw.json` | `8389bd4a650d1d70117029998a7abbf9078a56c6155dd877c0451fe82715db3b` |

The exact finite workload shape, seed, schedule, cache profiles, tokenization
boundary, and raw-output location are preserved in
`docs/research/2026-09-08_mlx-tuning-followup/workload.md`. The raw JSON files
retain all timed rows, correctness fields, output hashes, model identity, and
embedding responses' vector hashes. No failures or outliers were deleted.

## Decision

Do not adopt unequal-length `BatchKVCache` batching on this evidence: the
installed path is finite and preserves top-10 membership, but is rejected/not
validated by the applied numerical gate. Because the `1e-4` tolerance was not
pre-registered, this does not prove semantic incorrectness, impossibility, or a
wrong implementation. Exact-length grouping is a valid packaged API
experiment, but its sparse opportunity and mixed paired result do not justify
changing the current profile. Keep the earlier cap-specific hidden final-token
baseline as the measured choice. For embedding latency, prefer an external
periodic warm ping using the existing script when low tail latency matters, or
measure a dedicated service/runtime residency control before production use;
neither is integrated here. Treat endpoint and head results as diagnostic
evidence only.

## New fixed-shape `mx.compile` experiment

This was a new measurement-only experiment against the existing packaged
`model.model` backbone and the existing final-token hidden-state scorer. It did
not add a scorer, attention implementation, kernel, monkeypatch, source file,
package, or service change. The pinned runtime and model were unchanged:
`mlx-lm 0.31.3`, MLX runtime `0.32.2`, model snapshot
`5f324548f1d20c2b5a450f126fc6ef2fb1126524`, and the same two 34-document
payloads.

The installed API was inspected before the run. `mx.compile` supports
`compile(fun, inputs=None, outputs=None, shapeless=False)`; the experiment used
`mx.compile(model.model, shapeless=False)`, so each observed `(1, sequence_length)`
shape was compiled or reused as a fixed shape. The installed packaged call was
confirmed as `Qwen3Model.__call__(inputs, cache=None, input_embeddings=None)`;
no caller-supplied mask, position IDs, or padding was introduced. The model's
704 parameter leaves were `507` `mlx.core.bfloat16` and `197`
`mlx.core.uint32`; `all_parameter_leaves_fp32=false` and no fp32 parameter leaf
was observed. The smoke records retain scores and deltas for the first two
distinct lengths at each cap.

### Correctness gate and shape compilation

The predeclared promotion gate was maximum absolute score delta `<= 0.001`,
exact equality of the sorted top-10 index list, and zero flips at score `0.3`.
Finite cardinality was also required. Both smoke lengths at both caps returned
finite cardinality `1/1` and zero score delta:

| Cap | Smoke lengths | Reference / compiled scores | Max absolute delta |
|---:|---|---|---:|
| `850` | `155`, `171` | `0.1919327974` / `0.1919327974`; `0.0001355208` / `0.0001355208` | `0` |
| `2400` | `155`, `171` | `0.1919327974` / `0.1919327974`; `0.0001355208` / `0.0001355208` | `0` |

There were `30` unique shapes at cap `850` and `33` at cap `2400`, with two
lengths shared. The first-call records contain `59` additional shape events;
the cap-`2400` smoke calls for `155` and `171` reused shapes already observed
at cap `850`. Their observed first-call wall totals were `1.5295 s` for the
cap-`850` shape set and `2.2764 s` for the `31` new cap-`2400` shapes. These
values include the synchronized model/score call around the first shape, and
are not a claim about compiled-kernel count; no kernel-count instrumentation
was available or asserted. After all shapes were exercised, the recorded
cap-`850` memory snapshot was active `335,249,536` bytes, cache
`2,147,594,188` bytes, peak `865,288,328` bytes; cap `2400` was active
`335,249,652`, cache `1,074,037,892`, peak `1,338,773,696` bytes.

### Paired timing after compilation

Each cap used two warmups after all its shapes had been exercised, followed by
five seeded randomized paired repetitions. Full wall includes fresh
tokenization; synchronized GPU time is reported separately. No cache clear or
padding/truncation occurred between paired conditions.

| Cap | Condition | Full-wall p50 / p95 (s) | Tokenization p50 / p95 (s) | GPU p50 / p95 (s) |
|---:|---|---:|---:|---:|
| `850` | existing hidden final-token baseline | `1.2235 / 1.2349` | `0.01259 / 0.01439` | `1.2109 / 1.2226` |
| `850` | fixed-shape compiled backbone | `1.2229 / 1.2791` | `0.01265 / 0.01302` | `1.2101 / 1.2665` |
| `2400` | existing hidden final-token baseline | `2.5575 / 2.6563` | `0.03037 / 0.03621` | `2.5252 / 2.6201` |
| `2400` | fixed-shape compiled backbone | `2.5488 / 2.5872` | `0.02854 / 0.03300` | `2.5202 / 2.5542` |

All `20` timed records were finite and error-free. Every compiled timed record
had `34/34` finite scores, maximum absolute delta `0`, exact sorted top-10,
zero `0.3` flips, and passed the full promotion gate. Pairwise full-wall
compiled-minus-baseline results were:

- cap `850`: `3/5` compiled wins, median `-0.137%`, mean `+0.625%`;
- cap `2400`: `4/5` compiled wins, median `-1.346%`, mean `-0.823%`.

The cap-`2400` result is a small descriptive improvement in this five-pair
sample; cap `850` is effectively neutral and has a compiled p95 outlier of
`1.2791 s`. This is not an end-to-end MLX/server result and is not sufficient
to promote `mx.compile` as a production choice. It is evidence that this
packaged fixed-shape path can preserve the selected workload's scores, but not
a universal numerical or performance guarantee; the MLX compile documentation
also warns about recompilation as shapes vary and about the limits of
`shapeless` mode for shape-dependent masks.

### Exact invocation and retained evidence

The fresh command was an inline, non-source experiment from the repository
root; the output path was unique and immutable:

```bash
OUT="artifacts/research/2026-09-08_mlx-latency-eval/mlx-compile-fixed-shapes-20260908T120838Z.jsonl"
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" \
  .tmp/mlx-runtime/bin/python -B - "$OUT" <<'PY'
# Inline body: load the pinned model and payload, create
# compiled = mx.compile(model.model, shapeless=False), smoke the first two
# distinct token lengths, exercise every remaining fixed shape, then run two
# post-compilation warmups and five seeded paired repetitions. It records each
# model/score call, per-index scores, deltas, timing dimensions, and MLX memory.
PY
```

The actual run used cache limits `2 GiB` for cap `850` and `1 GiB` for cap
`2400`, seed `20260909`, synchronized evaluation, and a `90 s` per-call limit;
the inline body was intentionally not materialized as an application script.
The raw JSONL retains the complete score arrays for references, warmups, and
timed compiled/baseline rows, all shape first-call records, memory snapshots,
and the final status.

| Artifact | SHA-256 |
|---|---|
| `artifacts/research/2026-09-08_mlx-latency-eval/mlx-compile-fixed-shapes-20260908T120838Z.jsonl` | `c19a770be722ef06454c00f940fb3a04406d663ed47c79ce92ef09fcf9bd49d2` |

### External research and next candidates

The MLX compile reference documents fixed-shape recompilation behavior and
describes `shapeless=True` as unsafe for functions whose masks depend on
shape; this run therefore kept `shapeless=False` and did not pad inputs:
<https://ml-explore.github.io/mlx/build/html/usage/compile.html>. MLX issue
`#3384` reports that attention-mask kernels can differ numerically, so no
attention-mask drift proof is inferred from this exact-shape result:
<https://github.com/ml-explore/mlx/issues/3384>. The vLLM Metal document
describes an experimental Qwen3 reranker pooling alternative, but it was not
installed or tested here and is not an available-server claim:
<https://github.com/vllm-project/vllm-metal/blob/main/docs/text_embedding_pooling.md>.

The absence of a selected-row argument in the installed quantized matmul API
does not prove that slicing quantized weights is impossible. A future
controlled hypothesis could measure such a path only with a supported API and
the same numerical gate; no code or package change was made for it here.

Decision: retain the existing optimized hidden final-token baseline as the
default measured profile. Keep fixed-shape `mx.compile` as a narrowly validated
research candidate only; its small cap-`2400` timing signal does not justify a
production switch without broader shape coverage and independent repetition.