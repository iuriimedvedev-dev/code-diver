# M2a language lanes — 2026-10-07

Reviewed M2a investigation recorded in `.plans/2026-10-07_m2a-language-lanes.md`. Scope is delegated as follows: Go owns `symbols/go.rs` and its fixture; TS/JS owns `symbols/ts_js.rs` and its fixture; integration owns shared routing/builders, comparator filters, and comparison tests. A mandatory join must confirm boundaries/interfaces before coding assignments.

Completed: lane owners joined, dedicated Go/TS-JS extraction and shared routing/comparison tests implemented. Offline fmt, Clippy with warnings denied, and tests passed (130 distinct / 256 executions). Retained synthetic fixtures total 7735 bytes; only two redundant agent-created standalone TS harness sources were removed.

Measured Pier with exact STATUS config and full-content tokenization: Go 2038 files / 4076 items; TS/JS 507 files / 1014 items (TS subset 491/982). IDs, content, tokens and embed500 all 100%; no unmatched M2a categories. Whole-root hidden extras and Python AST differences remain outside M2a; see PARITY.md.

Knotgate comparison blocked: requested reference and parent directory missing, scanner config unavailable. Supplemental default build uses `--tokenize-content-chars 1000`; it is not parity. Correct cutoff is 2026-10-04 (earlier 2024 date was erroneous), excluding mtime >= 2026-10-05T00:00:00+02:00. Mtime is a heuristic, not snapshot proof; exact counts and commands are in STATUS.md.

User explicitly authorized exclusive documentation finalization and small logical local commits. No network, external writes, service changes, Python code-diver/strategy execution or push. Read-only Python JSON utilities were used solely for analysis. Data outputs stay uncommitted in `.tmp/` and `target`. Remaining action: provide Knotgate reference/config and verify snapshot identity before comparison; full SPEC acceptance and other language lanes remain pending.