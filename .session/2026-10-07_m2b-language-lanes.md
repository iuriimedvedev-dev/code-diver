# M2b language lanes — documentation reconciliation

- Reviewed `.plans/2026-10-07_m2b-language-lanes.md`, native Python/Rust modules,
  reference strategies and fixture provenance/READMEs; updated only STATUS,
  DECISIONS, PARITY and this session note. No source or fixture changes.
- Python: reference 122 files/244 records; built 124/248; all 244 common records
  equal in content, every token field, embed500 and ID/name/kind/path. No missing;
  4 extras (summary/manifest for hidden check.py/test_check.py). Strict ID-set
  equality is not 100%; comparison exits 1. M2a shared mismatches are historical.
- Scope: 126 .py, zero .pyi/.rs; two empty files emit nothing. Raw recursive
  47319/2602/110 counts include excluded trees, not scoped coverage; Rust is tmp.
- Pier/IntelliJ Rust references are empty: no real Rust parity claim. Golden
  21 Rust symbols; 8 tests each for Rust/Python, manually derived, not Python-run.
- Agent 5 reported 35 focused symbol tests, 5 integrations; full 142 per binary
  plus 5 integrations = 289 executions; offline fmt/check, Clippy all-target
  -D warnings and tests green. This documentation worker does not rerun them.
- Dependency-free tolerant Python parser chosen for offline availability and
  qualitative lighter dependency/build footprint, not measured size savings.
  Arbitrary SyntaxErrors, full decorator ast.unparse and Unicode XID/normalization
  remain limitations. Rust is a shallow regex reference port, not grammar-aware.
- Remaining: pinned/fresh Python snapshot and hidden-coverage acceptance;
  nonempty pinned Rust oracle/config; broader parser verification; prior M1/M2a
  gaps. Do not mark all SPEC gates complete. Reference revision/freshness unknown.
- Validation for this pass: documentation accuracy review and git diff --check
  only. No network, Python code-diver, external writes, data/build staging or
  commits; local prior outputs remain uncommitted.