# M2b language lanes

1. Read Python contract and native routing/CLI contracts.
2. Add Python (.py/.pyi) and Rust (.rs) case-insensitive dispatch, retaining empty-result generic fallback.
3. Add integration coverage for content, counts, and isolated mismatches; reproduce before wiring.
4. Run focused tests, formatting, offline clippy and full offline tests.
5. Inspect external configuration read-only; build native catalog into worktree .tmp and compare Python/Rust lanes against existing reference. Report counts, exact mismatch categories and blockers.

## Results

- Wired case-insensitive Python/Rust dispatch and CLI lanes; retained generic fallback. Integration test covers Python class/async method, restricted Rust visibility/trait impl, lane counts, content/token mutations isolated to the affected lane. Initial reproduction failed on generic Python symbol kinds.
- Commands from `native/code_diver_search_bin`: `cargo test --offline catalog_builder::symbols` (35 passed), `cargo test --offline --test catalog_cli` (5 passed), `cargo fmt`, `cargo clippy --offline --all-targets -- -D warnings`, `cargo test --offline` (142 tests in each of two binary targets plus 5 integrations, 289 executions; zero failures), `cargo fmt --check`, `git diff --check`. One initial fallback test used a TS declaration incorrectly; restored its original impl input and added a separate Rust fallback assertion.
- Removed the redundant agent-created three-file Rust harness after full native module tests passed. No lane module fixes were needed.
- Native build: `cargo build --offline --bin code-diver` then `target/debug/code-diver index --catalog-only --root /Users/iurii.medvedev/Work/sre-support-pier --config /Users/iurii.medvedev/Work/sre-support-pier/.code-diver/code-diver-pier.yml --out ../../.tmp/m2b/pier-native.jsonl` (16532 records; reference 16450).
- Comparisons: `target/debug/code-diver catalog-compare --reference /Users/iurii.medvedev/Work/sre-support-pier/tmp/rust-pier/rust_catalog.jsonl --built ../../.tmp/m2b/pier-native.jsonl --lane python` (exit 1) and same command with `--lane rust` (exit 0, empty).
- Python: reference 244 records/122 files; native 248 records/124 files; common 244. Content, all token fields, embed500, name, kind, path all 244/244 (100%). Standalone JSON inspection found zero differing fields on common records. Only category: IDs/extra, four records (summary/manifest each) for `repos/sre/.github/actions/changed-files/check.py` and `test_check.py`. No missing reference records. Strict whole-lane parity blocked by reference coverage, not common-record mismatches.
- Raw recursive root counts: .py 47319, .pyi 2602, .rs 110 (includes excluded temporary/virtualenv trees). Include-directory counts after standard excluded components: 126 Python files, zero .pyi/.rs; two empty `repos/sre-docs/tests/__init__.py` and `tests/sources/__init__.py` yield no catalog records. All 110 Rust files are under excluded tmp/.
- Pier and IntelliJ references contain zero .rs records; IntelliJ also has zero .py/.pyi. Nonempty real-world Rust parity cannot be established with these references; golden/unit and integration tests provide validation only.
- External root README and `.code-diver/code-diver-pier.yml` inspected read-only. Per-directory README/env files under rust-pier and rust-eval/intellij are absent. Shared `tmp/rust-eval/env.sh` identifies Pier and IntelliJ catalogs/base roots. No external scripts, Python code-diver, network or services executed; no external writes or commits.
- Local outputs: `.tmp/m2b/pier-native.jsonl`, `python-compare.txt`, `rust-compare.txt`, `tests.txt`; build outputs only in native target.