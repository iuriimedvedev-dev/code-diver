# Rust rewrite status

## M1 — 2026-10-07

Code commits: `d1d4a4d` (strict lint/format cleanup), `f1169c3` (M1 builder/tests).

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

104 unit tests per binary (208 executions, 104 distinct tests) and 2 CLI integration
tests passed. The suite includes 34 catalog-builder unit tests. The hidden-directory
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
This is an explicit allow-list candidate, not unqualified 100% set equality.

Python enumeration replay (deliberately does not request hidden inclusion):

```sh
"$BIN" index --catalog-only --root "$PIER" \
  --out .tmp/m1/pier-python-enumeration.jsonl \
  --config "$PIER/.code-diver/code-diver-pier.yml" \
  --include 'repos/**' --include 'kb/**'
"$BIN" catalog-compare --reference "$PIER/tmp/rust-pier/rust_catalog.jsonl" \
  --built .tmp/m1/pier-python-enumeration.jsonl --lane generic
```

Replay produces exactly 16450 items; dedicated files: 2667. Compare exits 0;
name/kind/path and embed500 text also match 11116/11116. Real catalog outputs
remain uncommitted under `.tmp/m1/` only. No Python, services or network were used.

### Remaining acceptance questions / limitations

- Owner acceptance is needed for the explicitly included hidden-file difference.
- Scanner YAML supports the existing block mapping/list format and flow lists,
  quoted strings, booleans, integers and nulls. Anchors/tags/multiline scanner
  values are rejected explicitly; full YAML support remains open. No cached YAML
  crate was available and fetching dependencies was forbidden. TOML is supported.
- Synthetic goldens are manually transcribed from the read-only Python templates,
  **not Python-generated frozen catalogs** (Python generation was prohibited).
  Independent QA should review their provenance and extend the oracle if allowed.
- M1 does not implement global config/env precedence, config-root path expansion,
  graph generation or embeddings/upserts; these remain later milestones.
- Generic manifest symbol-surface mode is supported; dedicated JVM surface
  templates and declaration-derived purposes/terms remain M2.

M1 code is implemented and locally validated with these explicit acceptance gaps;
do not mark all SPEC acceptance criteria complete. Parent must join this worker
before independent final QA.