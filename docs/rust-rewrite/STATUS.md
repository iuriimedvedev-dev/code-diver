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