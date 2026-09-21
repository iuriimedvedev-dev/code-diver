# MLX tuning follow-up — 2026-09-08

Fresh raw artifacts cover the packaged `BatchKVCache` probe, exact-length
grouping, quantized head, seed-43 paired timings, the earlier five-query
embedding probe, and `embedding_idle_probe_raw.json`.

Decision: do not adopt unequal-length `BatchKVCache` batching on this evidence.
It was finite with `10/10` top-10 membership at both caps, but max deltas were
`0.0307673` at cap `850` and `0.0223849` at `2400`; the applied `1e-4` numeric
tolerance was not pre-registered. Report this as rejected/not numerically
validated, not as proof of semantic incorrectness, impossibility, or a wrong
implementation. The raw exact top-10 lists are equal at `850` and differ in
order at `2400`; exact-length groups retain zero observed score delta, while
timing raw retains only `10/10` intersection rather than a separate candidate
list.

New embedding evidence: after `60 s` without requests from this workload, the
five serial new-query calls all succeeded with finite 1024-dimensional vectors
and the expected model. Times were `2.39728`, `0.01671`, `0.01801`, `0.01809`,
and `0.01976 s`; `/health` and `/v1/models` were fast readiness/model checks,
not warmed-model evidence. The first observed `52.4723 s` remains first-request
evidence from an already-running service, not startup/cold-start evidence; its
cause is unknown.

Targeted retained config/source inspection found `scripts/serve_embedder.sh`
uses vLLM pooling with no warmup, idle-unload, keep-alive, or model-residency
setting. The concrete available workaround is the existing
`scripts/keep_services_warm.py` periodic one-token ping; it was not started or
changed, and no production integration is claimed. No application, model,
package, service, or live configuration changes were made.

New fixed-shape compile experiment completed successfully. Installed support was
verified before execution: `mx.compile(fun, inputs=None, outputs=None,
shapeless=False)` and packaged `Qwen3Model.__call__(inputs, cache=None,
input_embeddings=None)`. The run used only `mx.compile(model.model,
shapeless=False)` plus the existing final-token hidden/`as_linear` score path;
no custom scorer, kernel, mask, padding, truncation, monkeypatch, package, or
application source change was introduced.

Raw: `artifacts/research/2026-09-08_mlx-latency-eval/mlx-compile-fixed-shapes-20260908T120838Z.jsonl`, SHA-256
`c19a770be722ef06454c00f940fb3a04406d663ed47c79ce92ef09fcf9bd49d2`.
Runtime/model identity remained pinned (`mlx-lm 0.31.3`, MLX `0.32.2`,
snapshot `5f324548f1d20c2b5a450f126fc6ef2fb1126524`). Parameter leaves were
`507` bfloat16 and `197` uint32; no fp32 parameter leaf was present.

Fresh counts: cap `850` had `30` fixed shapes and cap `2400` had `33` (two
shared); `4` smoke records, `8` warmups, and `20` timed records were retained.
All compiled smoke/timed scores were finite with cardinality `1/1` or `34/34`,
maximum delta `0`, exact sorted top-10 equality, and zero `0.3` flips. Full-wall
compiled-minus-baseline paired results were cap `850`: `3/5` wins, median
`-0.137%`, mean `+0.625%`; cap `2400`: `4/5` wins, median `-1.346%`, mean
`-0.823%`. Compilation/first-shape overhead was recorded separately: `1.5295 s`
for cap `850` and `2.2764 s` for the `31` new cap-`2400` shapes; no compiled
kernel count was claimed.

Decision: the compiled path is a narrowly validated research candidate, not a
production promotion. Retain the existing optimized hidden final-token baseline;
the cap-`2400` signal is descriptive and the cap-`850` result is effectively
neutral. External context retained in the report: MLX compile shape/shapeless
guidance, MLX issue `#3384` on possible attention-mask numerical differences,
and the untested experimental vLLM Metal Qwen3 pooling document. The absence
of a selected-row quantized-matmul argument remains only a future hypothesis,
not an impossibility claim.

Exact invocation identity:

```bash
OUT="artifacts/research/2026-09-08_mlx-latency-eval/mlx-compile-fixed-shapes-20260908T120838Z.jsonl"
HF_HUB_CACHE="$PWD/.tmp/mlx-model-cache/huggingface" .tmp/mlx-runtime/bin/python -B - "$OUT" <<'PY'
# Inline fixed-shape experiment; no source script was created.
PY
```