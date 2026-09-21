# MLX runtime tuning — 2026-09-08

## Scope and acceptance boundary

- Measure only the existing cached `mlx` `0.32.2` / `mlx-lm` `0.31.3` runtime on the M3 Max.
- Use the pinned `mlx-community/Qwen3-Reranker-0.6B-4bit` snapshot
  `5f324548f1d20c2b5a450f126fc6ef2fb1126524` and the two 34-document payloads
  in `artifacts/research/2026-09-08_metal-runtime/payloads_v2.json`.
- Do not edit application code, adapters, packages, services, or existing
  benchmark artifacts. Use finite inline invocations and write only tuning
  artifacts plus this plan, session record, and research report.
- Keep the live comparison at `http://127.0.0.1:18081/v1/rerank`; never use
  `localhost`, and never issue concurrent GPU inference.

## Staged method

1. Record runtime/model/payload hashes, exact model-card prompt, tokenization,
   Metal device, package versions, and safe system memory-pressure evidence.
2. Smoke-test sequential reference scoring and the packaged Qwen3 backbone
   hidden-output plus tied two-label projection. Reject any score-invalid path.
3. Probe supported batch sizes `1,2,4,8,16,34`; use length bucketing only when
   the existing attention mask/position behavior is validated on unequal lengths.
   Compare batched scores with sequential scores before collecting timing.
4. Screen allocator cache limits derived from measured working-set telemetry;
   do not change wired limits or purge the system cache. Persist JSON after
   each condition and retain failures/outliers; timeout pathological work at
   180 seconds.
5. Select the best measured valid configuration, then run two candidates and
   the correct sequential MLX reference plus live llama with randomized paired
   seed `42`: two warmups and at least five timed repetitions per cap.

## Measurements and validity

- Separate full request/tokenization-inclusive wall time, synchronized GPU
  forward/score time, and model-load time.
- Record per-run active/cache/peak MLX memory and safe system pressure stats.
- Require 34 finite per-index probabilities, max absolute score difference
  against same-weight sequential MLX, and sorted top-10 agreement. Report
  threshold `0.3` flips against MLX and llama separately; do not claim quality
  parity across quantization artifacts.
- Preserve all raw JSON incrementally and report p50, range, descriptive p95
  memory, and same-boundary ratios. Any blocked padding/head path is reported
  as blocked rather than implemented.