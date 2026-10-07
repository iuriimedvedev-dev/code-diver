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

### All mismatch categories (whole Pier catalog)

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