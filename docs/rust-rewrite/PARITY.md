# Rust catalog parity

## M2a — Go and TypeScript/JavaScript, 2026-10-07

Oracle: existing read-only Pier `tmp/rust-pier/rust_catalog.jsonl` under
`/Users/iurii.medvedev/Work/sre-support-pier`. Current root HEAD:
`b88c2267f7ea2289813ad1695ffa858ec1867707`; oracle generation revision unknown.
Reproduction commands and exact scanner config are in STATUS.md, M2a section.
Pier uses full-content tokenization; the 1000-character override belongs only
to the supplemental Knotgate build, not this reference comparison.

| Lane | Files (reference/built) | Items (reference/built) | ID equality | Content equality | Token equality | Embed500 equality |
|---|---:|---:|---:|---:|---:|---:|
| Go | 2038/2038 | 4076/4076 | 100% | 100% | 100% | 100% |
| TS/JS | 507/507 | 1014/1014 | 100% | 100% | 100% | 100% |
| TS subset | 491/491 | 982/982 | 100% | 100% | 100% | 100% |

Each file contributes summary and manifest items. TS/JS suffix distribution:
491 `.ts`, 14 `.js`, 2 `.mjs`. No missing or extra IDs, content differences,
token differences or metadata differences in either M2a lane. Equality is
measured over shared IDs with complete ID-set equality separately verified.
Embed500 is the first 500 Unicode characters of
`title: <name> | path: <path> | text: <content>`; read-only JSON analysis independently
checked this alongside all fields. Full content equality also implies raw-content
first500 equality. Both lanes exceed the requested 99% field target and meet the
100% ID target on this available reference, not all SPEC pinned snapshots.

### All mismatch categories (whole Pier catalog at M2a)

- Reference 16450 items, built 16532: zero missing, 82 extra items from 41
  explicitly included `.github` files. SPEC hidden traversal differs from Python
  enumeration; retain the documented M1 behavior, not an acceptance filter.
- 88 shared-item content and `tokenized_content` differences, all outside M2a:
  44 Python files with summary and manifest differences. Summary symbols differ
  in 44 files, summary terms in 42, manifest symbols in 44. The unported Python
  AST lane supplies signatures/kinds, while generic fallback uses unsigned
  `symbol` entries. All other shared fields match.
- No unmatched M2a category remains; no additional matching fix was necessary.

### Knotgate: blocked, no substitute parity claim

Requested oracle `/Users/iurii.medvedev/Work/knotgate/.code-diver/rust_catalog.jsonl`
and its parent directory are absent; scanner config is unavailable. STATUS.md
records a supplemental 1000-character-tokenized default scan and mtime eligibility
counts using the requested 2026-10-04 cutoff. Those counts are not reference
comparisons. Restore the reference/config and verify snapshot identity before
claiming Knotgate parity; mtime alone is insufficient.

### Golden provenance and scope

Synthetic Go, shallow TS/JS and integrated summary/manifest goldens live under
`native/code_diver_search_bin/tests/fixtures/`, with provenance READMEs. They are
manually derived from read-only Python implementations, not Python-generated
frozen catalogs. Fixture total is 7735 bytes. Real catalog outputs are uncommitted
under `.tmp/`. Other language lanes and full SPEC acceptance remain pending;
M1 generic results and acceptance gaps remain recorded in STATUS.md.

## M2b — Python and Rust, 2026-10-07

Same existing Pier oracle and exact scanner config as above; its source revision
is unpinned and freshness unknown. Current root HEAD does not establish oracle
snapshot identity. Commands are in STATUS.md. Prior agent 5 evidence, not a new
comparison run during this documentation pass:

| Python measurement | Reference | Built | Common |
|---|---:|---:|---:|
| Files | 122 | 124 | 122 |
| Summary records | 122 | 124 | 122 |
| Manifest records | 122 | 124 | 122 |
| All records | 244 | 248 | 244 |

| Category | Matching common records | Differences / unmatched records |
|---|---:|---:|
| ID on common records | 244/244 (100%) | 0 |
| Content | 244/244 (100%) | 0 |
| Every token field | 244/244 (100%) | 0 |
| Embed500 (definition above) | 244/244 (100%) | 0 |
| Name / kind / path (each) | 244/244 (100%) | 0 |
| Missing reference IDs | — | 0 |
| Extra built IDs | — | 4 (2 summary + 2 manifest) |

Read-only JSON inspection found no differing fields on common records. The
M2a 88 shared Python content/token differences are resolved on this comparison.
Only unmatched category: four extra IDs for summary/manifest pairs at
`repos/sre/.github/actions/changed-files/check.py` and
`repos/sre/.github/actions/changed-files/test_check.py`. Explicit hidden traversal
explains coverage; strict comparison exits 1. **Whole-lane ID sets are not 100%
equal**, even though all reference IDs are present and common fields are 100%.
Whole catalog remains 16450 reference / 16532 built; hidden-file extras remain
82 overall (78 generic, 4 Python), with no shared-field differences reported.

Scoped scanner inventory: 126 `.py`, zero `.pyi` and `.rs` after standard
exclusions; two empty files (`repos/sre-docs/tests/__init__.py`,
`tests/sources/__init__.py`) produce no records, explaining 124 output files.
Raw recursive 47319 `.py` / 2602 `.pyi` / 110 `.rs` includes excluded tmp and
virtualenv trees, not the roughly 120 scoped files; all raw Rust files are under
excluded `tmp/`. Raw totals are not eligible-lane coverage or parity evidence.

### Rust evidence and outstanding acceptance

Pier and IntelliJ references each contain **0 Rust records**; Pier built Rust
lane is also empty and exits 0. IntelliJ also has zero Python records. Empty-set
comparison is not a real-world Rust parity measurement or a 100% field score.
Rust validation is limited to a manually reference-derived **21-symbol golden,
8 Rust lane tests**, and routing/comparison integration coverage. Python has
**8 lane tests** and a manually derived golden; no Python reference code was
executed. The provenance README's deferred-validation notes describe its worker
stage; subsequent joined agent 5 validation is recorded in STATUS.md.

Agent 5 reported 35 focused symbol tests, 5 integrations, and full offline
142 tests per binary + 5 integrations (289 executions), with fmt/fmt-check and
all-target Clippy `-D warnings` green. Tests are not independent Python-executed
goldens and cannot establish missing real-reference coverage. Obtain a nonempty
pinned Rust oracle/config; confirm Python oracle freshness/snapshot identity and
resolve hidden-file coverage acceptance. Verify broader Python SyntaxError,
decorator `ast.unparse` and Unicode identifier cases (DECISIONS.md), and retain
M1/Knotgate/other milestone blockers. **Not all SPEC gates are met.** No data or
build outputs are committed; this pass changes documentation only.