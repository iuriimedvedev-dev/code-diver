# Session: Hub Prior Protect Top
Date: 2026-09-02

## Decisions
- Add `hub_prior_protect_top` setting to `CrossEncoderRerankConfig` to pin the top SearchResults during hub prior adjustment.
- Default value is 0 (current behavior).
- Implementation splits scores into protected head and adjustable tail.
- Trace event `cross_encoder_hub_prior` will include `protect_top`.

## Status
- Configuration changes planned.
- Implementation logic designed.
- Evaluation metrics will be compared against rebaseline.
