# MLX runtime tuning — 2026-09-08

## Decision

Run a bounded measurement-only tuning study using packaged MLX APIs. The
baseline remains the model-card sequential scorer; no application integration
or production switch is in scope.

## Initial evidence

- `mlx` `0.32.2`, `mlx-lm` `0.31.3`, Metal available, pinned snapshot
  `5f324548f1d20c2b5a450f126fc6ef2fb1126524`.
- Qwen3 `Model.__call__` materializes vocabulary logits, while its packaged
  backbone returns normalized hidden states and tied `embed_tokens.as_linear`
  is available for an experimental two-label projection.
- `mx.get_active_memory`, `get_cache_memory`, `get_peak_memory`,
  `set_cache_limit`, and `clear_cache` are supported. `batch_generate` is not
  a reranker scoring API and is excluded.

## Guardrails

Use the existing payloads without truncation, pin `HF_HUB_CACHE` and revision,
preserve `HOME`, keep GPU calls serial, use only finite inline commands, and
save incremental artifacts under `artifacts/research/2026-09-08_mlx-tuning/`.

## Final measured decision

- Best cap `850`: packaged final-hidden scorer with a `2 GiB` MLX free-cache
  limit, p50 `1.976 s` full wall across five timed repetitions.
- Best cap `2400`: the same scorer with a `1 GiB` limit, p50 `4.052 s`.
- Same-weight sequential MLX validity: 34/34 finite scores, top-10 `10/10`,
  zero `0.3` threshold flips; max score deltas `0.003628` and `0.012109` for
  caps `850` and `2400`.
- Live llama comparison is timing/diagnostic evidence only: `9/10` top-10
  intersection, `2/34` and `3/34` threshold flips, with different weights and
  an unverified server-side prompt.
- Unequal-length batching is blocked by the installed API: no external mask or
  position argument exists, and actual padding changed one smoke score by
  `0.020872`. Batch sizes above one were not timed or emulated with custom code.
- Float32 two-logit softmax correction was measured separately from speed; for
  each MLX timed configuration, all 340 rows differed from bfloat16 softmax,
  with maximum correction `0.0037545`.

## Validation status

The complete confirmation used two warmups and five randomized seed-42 timed
repetitions per cap/configuration. There were 56 retained runs, no timeout or
error, and no service/application changes. Detailed timing, tokenization,
synchronized GPU timing, memory, schedules, HTTP responses, and reusable
invocation notes are in `docs/research/2026-09-08_mlx-tuning.md` and
`artifacts/research/2026-09-08_mlx-tuning/tuning_raw.json`.