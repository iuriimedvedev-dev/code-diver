# Rust rewrite status

## M1 — 2026-10-07

Code commits: `d1d4a4d` (strict lint/format cleanup), `f1169c3` (M1 builder/tests).
Corrective commits: `dd25dbc` (fixture location), `b22e465` (schema/diagnostics),
`b8f84c6` (fail-fast config and direct load tests).

Implemented catalog-only indexing, deterministic ignore-aware scanner, summary and
manifest templates, generic/Markdown symbols, SHA1 IDs, tokenized fields, config
switches, JSONL comparison, synthetic template goldens and CLI tests. Both
`code-diver` and compatibility `code_diver_search_bin` binaries are built. Existing
search/MCP CLI behavior is retained. Network/index upsert and dedicated extractors
are not part of M1.

Validation (offline, macOS; Cargo toolchain 1.98.1):

```sh
cd native/code_diver_search_bin
cargo fmt --check
cargo clippy --offline --all-targets -- -D warnings
cargo test --offline
```

Independent initial QA confirmed 106 distinct tests / 210 executions. After
corrections, 108 unit tests per binary plus 3 CLI integration tests passed:
**111 distinct tests, 219 executions**. The suite includes 38 catalog-builder unit
tests. The hidden-directory
and noncompact-summary regressions were first reproduced failing, then fixed.
Formatting and mechanical lint cleanups in the existing crate are necessary for
the required crate-wide checks; no ranking logic was intentionally changed.

### Measured Pier parity

Read-only root: `/Users/iurii.medvedev/Work/sre-support-pier`; current HEAD
`b88c2267f7ea2289813ad1695ffa858ec1867707`. Reference:
`tmp/rust-pier/rust_catalog.jsonl`, 16450 items. Its generation revision is not
known; the current working tree was scanned without changing it.

From this worktree root:

```sh
BIN=native/code_diver_search_bin/target/debug/code-diver
PIER=/Users/iurii.medvedev/Work/sre-support-pier
mkdir -p .tmp/m1
"$BIN" index --catalog-only --root "$PIER" --out .tmp/m1/pier.jsonl \
  --config "$PIER/.code-diver/code-diver-pier.yml"
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m1/pier.jsonl --path-prefix kb/ --lane generic
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m1/pier.jsonl --lane generic
```

| Measurement | Reference | Built | Shared IDs | Equal content | Equal tokens |
|---|---:|---:|---:|---:|---:|
| kb/, generic | 1242 | 1242 | 1242/1242 | 1242/1242 | 1242/1242 |
| Whole root, generic, SPEC hidden inclusion | 11116 | 11194 | 11116/11116 | 11116/11116 | 11116/11116 |
| Whole root, generic, Python enumeration replay | 11116 | 11116 | 11116/11116 | 11116/11116 | 11116/11116 |

Default/config scan: 16532 items, 8266 files, **2669 dedicated-language files**
using generic fallback (no claim of M2 content parity). There are 82 new items
from 41 `.github` files: 78 generic items and 4 dedicated items. The Python
reference omitted these despite including `.github/**`, because its rg command
never enables hidden traversal. The SPEC explicitly requires hidden traversal
when included, so the strict whole-root comparison **exits 1** for these extras.
There are no missing reference IDs and no generic content/token differences.
Whole generic IDs are **not 100% equal overall**: 11116 reference versus 11194
built. Preserve SPEC 5.1 hidden inclusion, not an acceptance workaround or filter.
Comparator output now samples extra IDs and diagnoses content sections,
first token fields and metadata with path/ID and reference/built values. Missing
or wrong-typed required token/symbol arrays fail JSONL loading, even on both sides.

Python enumeration replay (supplemental investigation only, **not acceptance**;
deliberately does not request hidden inclusion):

```sh
"$BIN" index --catalog-only --root "$PIER" \
  --out .tmp/m1/pier-python-enumeration.jsonl \
  --config "$PIER/.code-diver/code-diver-pier.yml" \
  --include 'repos/**' --include 'kb/**'
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m1/pier-python-enumeration.jsonl --lane generic
```

Replay previously produced exactly 16450 items; reference dedicated files: 2667
(default Rust: 2669). Compare exited 0;
name/kind/path and embed500 text also match 11116/11116. Real catalog outputs
remain uncommitted under `.tmp/m1/` only. No Python, services or network were used.

### Remaining acceptance questions / limitations

- Owner acceptance is needed for the explicitly included hidden-file difference.
- Scanner YAML supports the existing block mapping/list format and flow lists,
  quoted strings, booleans, integers and nulls. Anchors/tags/multiline scanner
  values are rejected explicitly; full YAML support remains open. No cached YAML
  crate was available on corrective review and fetching dependencies was forbidden.
  Unsupported inline scanner mappings, duplicate sections, nested scanner values,
  unknown scanner keys and wrong-typed settings fail fast. Direct `load_config`
  tests cover all supported builder settings and caps, both compact modes,
  max-symbol limits and the tokenization switch. TOML parsing is supported;
  complete application configuration is not an M1 claim.
- Synthetic goldens are manually transcribed from the read-only Python templates,
  **not Python-generated frozen catalogs** (Python generation was prohibited).
  They live in `native/code_diver_search_bin/tests/fixtures/` (2890 bytes including
  provenance README, below 200KB). Existing Pier reference is the independent
  oracle; synthetic fixture independence remains limited.
- M1 does not implement global config/env precedence, config-root path expansion,
  graph generation or embeddings/upserts; these remain later milestones.
- Generic manifest symbol-surface mode is supported; dedicated JVM surface
  templates and declaration-derived purposes/terms remain M2.

M1 code and corrections are locally validated with these explicit acceptance gaps;
do not mark all SPEC acceptance criteria complete. Initial independent QA completed;
parent must join this corrective worker before any final independent re-review.

## M2a — 2026-10-07

Implemented dedicated Go and TS/JS shallow extractors, generic fallback when a
dedicated result is empty, all eight TS/JS routing suffixes, and `catalog-compare`
lanes `go` and `ts-js`. Synthetic goldens and routing/comparison tests are included.
M2a implementation and Pier QA are complete; Knotgate acceptance is blocked.

Actual offline validation passed: `cargo fmt`, then
`cargo clippy --offline --all-targets -- -D warnings` and `cargo test --offline`.
After removing two redundant agent-created standalone TS harness sources,
`cargo fmt --check`, Clippy and tests passed again. Counts: **126 unit tests per
binary + 4 integration tests = 130 distinct tests / 256 executions**, no failures
or ignored tests. Duplicate-ID stderr is expected from a negative integration
test. All retained fixtures total **7735 bytes**, below 200 KB.

### Measured M2a Pier parity

Same read-only Pier root, HEAD and reference as M1 above; the reference generation
revision remains unknown. Exact STATUS scanner config, not blanket includes:

```sh
BIN=native/code_diver_search_bin/target/debug/code-diver
PIER=/Users/iurii.medvedev/Work/sre-support-pier
mkdir -p .tmp/m2a
"$BIN" index --catalog-only --root "$PIER" --out .tmp/m2a/pier.jsonl \
  --config "$PIER/.code-diver/code-diver-pier.yml"
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m2a/pier.jsonl --lane go
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m2a/pier.jsonl --lane ts-js
```

| Lane | Reference/built files | Reference/built items | IDs | Content | Tokens | Embed first500 |
|---|---:|---:|---:|---:|---:|---:|
| Go | 2038/2038 | 4076/4076 | 100% | 100% | 100% | 100% |
| TS/JS | 507/507 | 1014/1014 | 100% | 100% | 100% | 100% |
| TS subset | 491/491 | 982/982 | 100% | 100% | 100% | 100% |

TS/JS contains 491 `.ts`, 14 `.js` and 2 `.mjs` files, explaining the expected
TS491 count. Both CLI comparisons exit 0. No unmatched M2a categories exist.
Read-only JSON analysis checked every shared field; see PARITY.md for the
whole-catalog differences and the independent first500 definition.

### Knotgate blocker (not parity)

`/Users/iurii.medvedev/Work/knotgate/.code-diver` and its requested
`rust_catalog.jsonl` do not exist (`stat` evidence). No matching scanner config
was found in root inspection or tracked code-diver paths. Reference comparison
cannot run; restore/provide the reference and its config before acceptance.

Supplemental default-config build only:

```sh
"$BIN" index --catalog-only --root /Users/iurii.medvedev/Work/knotgate \
  --out .tmp/m2a/knotgate-current-default-1000.jsonl \
  --tokenize-content-chars 1000
```

This produced 9220 items / 4610 files, including Go 6/3 and TS/JS 7284/3642.
The requested cutoff is **2026-10-04**, not 2024. Excluding mtime at or after
`2026-10-05T00:00:00+02:00` (end of that local calendar day) removes 182 files,
including 160 TS/JS and zero Go. Eligible totals are 8856 items / 4428 files;
TS/JS 6964/3482, Go 6/3. These are eligibility counts, **not parity**. Copies and
checkouts can alter mtime; this heuristic cannot establish snapshot identity.
Outputs remain uncommitted under `.tmp/m2a/` and Cargo `target`; no network,
services, external writes or Python code-diver/strategy execution were used.

## M2b — Python and Rust, 2026-10-07

Implemented case-insensitive `.py/.pyi` and `.rs` symbol dispatch and comparator
lanes `python` and `rust`, preserving generic fallback for empty dedicated results.
Python uses a dependency-free tolerant token/suite parser; Rust ports the Python
strategy's shallow line regexes, not a Rust grammar. Limitations and rationale
are recorded in DECISIONS.md; this is not a full Python AST compatibility claim.

Agent 5 reported green offline validation: `cargo test --offline
catalog_builder::symbols` (35 focused tests), `cargo test --offline --test
catalog_cli` (5 integrations), `cargo fmt`, `cargo fmt --check`,
`cargo clippy --offline --all-targets -- -D warnings`, and `cargo test --offline`.
Full suite: **142 unit tests per binary + 5 integrations = 147 distinct tests /
289 executions**. Python and Rust each have 8 lane unit tests; the Rust golden
contains 21 symbols. Goldens are manually reference-derived, not Python-executed.
These are prior worker results, not tests rerun by this documentation update.

### Measured M2b Pier evidence

Same read-only root/config/reference as above; reference source revision is
unpinned and freshness unknown. Agent 5 built 16532 records against 16450 in the
reference, with full-content tokenization:

```sh
BIN=native/code_diver_search_bin/target/debug/code-diver
PIER=/Users/iurii.medvedev/Work/sre-support-pier
"$BIN" index --catalog-only --root "$PIER" \
  --config "$PIER/.code-diver/code-diver-pier.yml" --out .tmp/m2b/pier-native.jsonl
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m2b/pier-native.jsonl --lane python
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m2b/pier-native.jsonl --lane rust
```

Python: reference **122 files / 244 records**, built **124 files / 248 records**.
All 244 common IDs match in content, every token field, embed500, name, kind and
path (**244/244, 100%**). No missing IDs; four extras are summary/manifest pairs
for `repos/sre/.github/actions/changed-files/check.py` and `test_check.py`.
Strict whole-lane ID-set equality is **not 100%**; comparison exits 1. Preserve
SPEC hidden traversal rather than filter extras. Per-category counts: PARITY.md.

Scoped include-directory inspection after standard exclusions found **126 `.py`
files, zero `.pyi`, zero `.rs`**. Two empty files,
`repos/sre-docs/tests/__init__.py` and `tests/sources/__init__.py`, produce no
records, leaving 124 built Python files. Raw recursive counts were 47319 `.py`,
2602 `.pyi`, 110 `.rs`; those include excluded temporary/virtualenv trees and
are irrelevant to the roughly 120 scoped files. All 110 Rust files are under
excluded `tmp/`.

Pier and IntelliJ references both contain **zero Rust records** (IntelliJ also
has zero Python records). Pier's empty Rust comparison exits 0 but establishes
no nonempty real-world Rust parity; only golden/unit/integration validation is
available. Required next verification: a nonempty pinned Rust reference/config,
Python reference snapshot/freshness confirmation and hidden-coverage acceptance,
broader Python grammar/decorator/Unicode cases, plus existing M1/M2a blockers.
**Not all SPEC gates are met.** Local data/build outputs remain uncommitted under
`.tmp/m2b/` and Cargo `target`; no network, services, external writes or Python
code-diver execution. This documentation pass ran only `git diff --check`.

## M2c — JVM and C/C++, 2026-10-07

Implemented dedicated JVM/C/C++ extraction, JVM summary purpose/terms and manifest
surface integration, case-insensitive routing, comparator lanes and strict lane
isolation tests. Java/Kotlin/Kotlin scripts are dedicated; Scala stays generic.
Manual reference-derived fixtures are not Python-generated catalogs.
**Implementation is available; the >=99% real-reference target is NOT achieved
and M2c acceptance is not complete.**

Joined worker validation: fmt-check, offline all-target Clippy with `-D warnings`,
offline tests and release build green. The saved test log confirms **163 unit
tests per binary x 2 + 6 integrations = 332 executions / 169 distinct tests**,
zero failures or ignored tests. This documentation pass does not rerun Cargo.

IntelliJ full-root build: **136152 reference / 135404 built records**. Closest
scanner configuration is `configs/intellij/intellij-h66b-budget.yml` in the
read-only Python code-diver checkout; literal exact config identity is unproven.
The duplicate champion has identical scanner settings. Reference source revision
and freshness are unknown. JVM has 128706 reference / 129138 built / 125984 common
records, 2722 missing and 3154 extra. Common content is **93.0721%**, tokens
**93.0952%**, first500 embedding text **98.7721%**. Strict JVM comparison fails;
C/C++ is 0/0 and supplies no real-reference coverage. See PARITY.md for all counts
and examples, not a stale-reference waiver of acceptance.

An independent stdlib script replayed current Python rules without importing or
executing code-diver: zero audited-section differences across 64569 JVM files.
All 8728 common-content mismatches match current rules; 6296 have demonstrably
absent old source rows, while 2432 remain historically unattributed. Current-rule
agreement cannot prove the historical reference/config was generated identically.

Build elapsed **30.86s**, maximum RSS **2934030336 bytes (2.73 GiB)**. Existing
whole-catalog retention remains a limitation: 46271283 token Strings require
1.11 GB of headers alone; retained payload floor is 1.58 GiB before allocator,
capacity and other overhead. Streaming is needed, outside this milestone's scope.
Reports/catalogs/build outputs remain ignored and uncommitted under `.tmp/` and
Cargo `target`. Obtain pinned source/config and nonempty C/C++ evidence, resolve
historical attribution and meet the real-reference target before acceptance;
earlier milestone blockers also remain open.