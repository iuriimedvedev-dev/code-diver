# Final integration QA — 2026-10-07

## Decisions
- User clarified mandatory M6 CI is the native CLI, not the optional PyO3
  extension. Stock Rust runners validate only code_diver_search_bin; no Python
  installation/download was forced. Both crate versions remain 0.5.0.
- Exclusive worktree scope; no other repositories, real cluster, push or publish.
  Earlier investigation's Python-fixture execution is recorded in its own session;
  final integration runs use Rust helpers, not Python. HOME was not overridden.
- Stage exact implementation files only; preserve old unrelated plan/session
  artifacts and exclude all ignored .tmp/data outputs.
- Runtime commit: 4b090e3. Rust-only fixture commit: ac9943d. Packaging/docs and
  this report are committed together afterward, with required co-author trailers.

## Final validation
- CLI fmt and offline all-targets Clippy (-D warnings) pass; full offline tests:
  **960 passed, 18 suites, zero failed/ignored**. This supersedes 950 and counts
  repeated module suites in both binary targets/integration targets, not unique
  definitions. Log: .tmp/final-qa/bin-final.log.
- Acceptance **9/9** mocks pass: sequence, failure cleanup, credentials/argv safety
  and HOME isolation. Shellcheck, bash -n, diff whitespace and both crate fmt
  checks pass. actionlint unavailable; CI/release workflows manually reviewed.
- Optional extension offline test/Clippy previously failed before compilation on
  uncached pyo3. Optional validation is documented separately, not a CLI gate.
- Test helper is harness=false under [[test]], not a shipped binary. Version
  displays use Cargo; Cargo/lock/optional pyproject agree at 0.5.0.

## Evidence and seven coverage groups (not authoritative defect numbering)
1. PASS fix: extracted actual baseline Report::record compiled with rustc --test;
   baseline fails because PASS retains repair hint, current passes.
2. Progress spam: compiled baseline/current callbacks; 1,001 updates produce
   baseline 1,001 lines (fails bound), current 21 (passes).
3. Reranker consistency: isolated full baseline Rust crate test fails actual
   doctor ctx4096 guidance against daemon default ctx16384; current passes.
   Additional baseline test fails absent manifest serving ctx; current passes.
4. No-register: isolated baseline Rust tests fail persisted opt-out roundtrip and
   doctor registration SKIP; both current tests pass. Current full acceptance also
   covers setup persistence, doctor and retained non-registration checks. Baseline
   setup end-to-end itself was not rerun; do not claim that extra reproduction.
5. Diagnostics: reviewed quoted errors in setup/update-index/daemon/doctor.
   Generic ownership, locking, snapshot, resource and artifact messages now carry
   safe cause/path and repair action. Daemon type/message codes remain stable with
   additive fix guidance; doctor-specific failures retain paired repair hints.
   New ledger, unsafe-directory/missing-snapshot, missing-manifest and daemon-code
   tests pass. An isolated baseline missing-manifest diagnostic test fails while
   current passes; this is recovered baseline evidence, not an earlier worktree run.
6. Publication fixtures: required hashed ranker files added to setup/updater HTTP
   fixtures; initial failures observed then fixed. Current ranker publication/
   metadata regressions pass, without claiming new baseline reproduction.
7. Rust-only fixture/QA migration: controlling-tty and daemon/host helpers use Rust,
   guarded by no_python_helpers. Initial fmt/Clippy defects observed and repaired;
   updater test lock release and macOS socket blocking corrected.

## Security and limits
- Including raw Qdrant causes introduced a secret leak detected by the unchanged
  acceptance assertion. Replaced untrusted service/host causes with safe categories
  and guidance, then full tests passed; no assertions weakened or tests skipped.
- Baseline evidence is actual execution, not source-only inference, via git show/
  archive b66d801 and isolated copies; no checkout/reset. Scripts and logs remain
  uncommitted under .tmp/final-qa (pass-fix, progress, settings-repro.js/logs).
- Four-target builds, real shared collection acceptance and release publication
  remain unperformed. External health command probes still lack timeouts (existing
  finding); no unrelated behavior changes were attempted in this diagnostics task.