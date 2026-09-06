# Research Campaign: Full E2E 1065 (Selective Second Pass)

## Status Update
- **Campaign**: attempt-04
- **Progress**: 782/1065 pairs completed.
- **Outcome**: Paused due to 7-hour hard time limit (hard_cap).
- **Time spent**: 24,967s (~6.93h).
- **Backend**: llama-server on port 18081 (Metal/Threads=12).
- **Fixes applied**: Fixed inaccuracies in runtime reporting (n_ctx 40960 verified).
- **Blockers**: None, execution was healthy.

## Artifacts
- Results: `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/attempt-04/`
- Detailed report: `docs/research/2026-09-05_full-e2e1065-selective-second-pass.md`

## Next Steps
- Resume remaining 283 pairs in the next session using the `--resume` flag.
