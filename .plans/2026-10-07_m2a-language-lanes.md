# M2a language lanes

## Reviewed plan

- **Go lane:** owns `native/code_diver_search_bin/src/catalog_builder/symbols/go.rs` and its synthetic Go fixture. Match the reviewed Python Go strategy, including recognizer order, grouped types, receiver methods, signatures/end behavior, sorting, and fallback-compatible behavior.
- **TS/JS lane:** owns `native/code_diver_search_bin/src/catalog_builder/symbols/ts_js.rs` and its synthetic TS/JS fixture. Cover the reviewed eight suffixes and preserve Python recognizer order and intentionally shallow regex behavior.
- **Integration lane:** owns shared symbol routing/builders, comparator lane filters, and comparison/CLI tests. Wire the language lanes without altering generic fallback or existing catalog behavior.
- **Mandatory join:** do not begin implementation assignments until all lane owners have reviewed and agreed on these boundaries and shared interfaces.

## Decisions and gates

- Keep synthetic fixtures under 200 KB. The user target is at least 99% parity for each lane; the reviewed SPEC sets a stricter pinned-snapshot target of 100% ID and content equality, with documented quirks. Report measured parity and mismatch categories rather than hiding differences.
- After the join, delegated QA runs offline `cargo fmt --check`, `cargo clippy --offline --all-targets -- -D warnings`, and `cargo test --offline` in `native/code_diver_search_bin`.
- Build Pier with the documented config and full-content tokenization; run Go and TS/JS lane comparisons. The `--tokenize-content-chars 1000` override belongs to Knotgate only. Knotgate: ignore changes after 2026-10-04, interpreted as end of the local calendar day. Do not execute Python code-diver/strategies, use network, or modify external repositories.
- Triage and fix mismatch categories, then update measured results in `docs/rust-rewrite/STATUS.md`, `PARITY.md`, and `DECISIONS.md` as appropriate. Make small, logically scoped commits; do not commit without authorization.

## Completion / handoff

- Lane owners joined; implementation, integration and offline QA completed.
- Pier Go 2038 files / 4076 items and TS/JS 507 files / 1014 items match 100%
  for IDs, content, tokens and embed500. TS subset: 491 files / 982 items.
- 130 distinct tests / 256 executions pass; fixtures total 7735 bytes.
- No unmatched M2a categories; whole-root hidden extras and unported Python AST
  differences are documented in PARITY.md, not silently filtered.
- Knotgate reference/config missing: comparison blocked. Supplemental scan and
  2026 cutoff eligibility counts cannot establish parity or snapshot identity.
- User authorized exclusive finalization and small local commits; no push.
  STATUS/PARITY/DECISIONS and the session record capture results and limitations.