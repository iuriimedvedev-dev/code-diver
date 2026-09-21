# Metal Runtime Session Record — 2026-09-08

## Completed

- Recomputed provenance from the actual durable JSON files.
- Retracted the earlier unreliable `850` and `2400` payload hashes.
- Copied seven own JSON evidence files byte-for-byte into `artifacts/research/2026-09-08_metal-runtime/`.
- Confirmed the corrected raw data contains `8` warm-up and `12` timed rows, with `0` errors and `34` finite results per timed request.
- Kept the initial malformed-document run separate: `20/20` HTTP 400 failures.
- Recorded the owned-server shutdown proof and the untouched baseline health result.

## Provenance correction

`payloads_v2.json` file SHA-256 is `faa2ebe03efafb652705ae30268057fa5f75b98c3117fe2e587e391a06748ed9`.

The canonical query/documents hashes are `f20cee9121bf29c960e07b4317a084ccba4a9967f61ee3676ee16a5b18f2ffdb` (`850`) and `264139e9b33cec14508fe53a6e03dd66eccefdd1201959d3c861fb4addf75dd8` (`2400`). The actual serialized request-body hashes, including the model and frozen-entry metadata, are `31ec2a833ea459451e09d4a08672054b58921e5e0c44ecdc63a3ebbf81ecf9dc` and `26955d85bb485d8078c9ef8552ea0163787658243bcbca07711216df0d12c2e6`, respectively.

## Interpretation

The explicit Metal profile was faster at cap `850` and slower at cap `2400` in this tiny sample, but it also changed slots from baseline `4` to isolated `1`. The result cannot support a Metal-only speed claim. Score deltas were at most `0.0005682558` (`850`) and `0.0009218752` (`2400`), with identical top-10 rankings in all three descriptive joins per cap.

This was a llama.cpp/GGUF comparison, not an MLX comparison. No source or application configuration change is justified by this evidence; MLX integration remains a separately approved coding task if desired.