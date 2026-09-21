# Metal Runtime Handoff Plan — 2026-09-08

## Purpose

Preserve trustworthy provenance for the completed isolated Qwen3 reranker experiment without changing application code or `code-diver.yml`.

## Evidence disposition

- Copy only the seven experiment JSON files created in the durable experiment directory into `artifacts/research/2026-09-08_metal-runtime/`.
- Preserve both attempts: the first object-document attempt (`20/20` HTTP 400) and the corrected string-document attempt (`8` warm-ups plus `12` timed requests, `0` errors).
- Verify destination byte hashes against the durable originals.
- Distinguish the full `payloads_v2.json` file hash from the embedded canonical payload hash and the actual HTTP request-body hash.

## Experiment facts

- Fixed query, exactly `34` explicitly selected tracked project files; no catalog retrieval and no acceptance labels.
- Existing GGUF and baseline `18081` were retained.
- Owned server used `127.0.0.1:18082`, `MTL0`, `--gpu-layers all`, `--op-offload`, batch/ubatch `2048`, context `40960`, and `--parallel 1`.
- Baseline had previously reported four slots; isolated server reported one. Treat timing as confounded, not as a GPU causal result.
- One seeded block order was used, not counterbalanced random paired trials.

## Handoff decision

Report the corrected descriptive timings, score deltas, and unchanged top-10 rankings only with the above limitations. Do not claim MLX performance or approve MLX source integration from this run: the run used only `llama-server` and the active `.venv` lacked `mlx`/`mlx_lm`.

## Completion proof

The owned process stop check retained `18082_listening=no`; the untouched baseline retained `{"status":"ok"}` on `18081`. No log inspection, install, source edit, root configuration edit, or service restart was performed.