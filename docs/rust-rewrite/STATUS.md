# Rust rewrite status

M3 core implementation and shared transport are complete and independently
validated. Full SPEC acceptance is not claimed: token audit candidate counts are
estimates, not exact tokenizer parity; the synthetic request fixture is manually
derived, not an independently recorded Python request. Final QA authorizes logical
commits only, with no push or committed scratch/data outputs.

## Authoritative independent final QA — 2026-10-07

- After implementation join, actual fmt check, offline all-target Clippy
  `-D warnings`, offline tests and build passed: **364 executions / 191 distinct
  tests**, zero failures/ignored. Log: `.tmp/m3-qa/join-test.log`.
- Actual `.tmp/m3-qa/final-tls.mjs` repeat confirms `search --config` rejects
  untrusted HTTPS by default; custom CA and insecure mode each return five
  reranked results, with two real CE calls each. Insecure warnings present;
  embedding/Qdrant credentials isolated and no credentials sent to CE.
  **The earlier CE TLS blocker is closed.** Evidence: `final-tls/auth-tls.json`
  and `.tmp/m3-qa/join-tls-transcript.log`. The JSON now records this latest run;
  earlier failure history remains below and in `final-tls-transcript.log`.
- Script also repeated initial60, unchanged0/0/0 with untouched local outputs,
  changed model/prefix rejection, edit/delete retained60 and prune58. Owned
  `zz_m3_4532ebf57edf` deleted and verified HTTP404. Existing collections untouched;
  no restarts, Python execution, Rust edits or commits by QA.
- Prior Pier dry-run evidence retained; transport correction cannot alter its
  scanner/content diff. Remaining M3 evidence gaps: exact tokenizer parity and
  an independently recorded Python request fixture only. 80-query evaluation
  is not a user requirement. Historical unresolved states below are superseded.

## Final M3 transport correction — 2026-10-07

- Supersedes the open TLS/flakiness defects in the joined QA section below.
  Credential-free CE now uses the shared CA/insecure/redirect client policy.
  Loopback HTTPS search regression checks strict rejection, CA and insecure
  success, actual CE calls, isolated service credentials and insecure warnings.
  CA search failed at CE before the fix. Test requires Node and OpenSSL.
- Confirmed mock root cause: macOS accepted sockets inherited nonblocking mode;
  delayed headers caused empty/incomplete responses and connection resets.
  Delayed-header reproducer failed before restoring blocking accepted sockets.
  Handlers have bounded read/write timeouts and are joined at server teardown.
  Timeout test retains its diagnostic/no-write/time-bound assertions, now using
  100ms requests versus 500ms server delay rather than 5ms versus 50ms.
- fmt, offline all-target Clippy `-D warnings`, full offline tests and diff-check
  pass: **191 distinct / 364 executions**, zero failures/ignored. Contention
  stress: 24 M3 suites, four concurrently, **264/264 executions passed**; the
  same stress reproduced transport failures before the fix.
  Full suite repeat passed another 364 executions; HTTPS targeted repeat 5/5.
- No commits, Python execution, real-service writes or QA artifact modifications.
  Parent must join implementation before independent live TLS smoke repeat via
  `.tmp/m3-qa/final-tls.mjs` (QA owns artifacts and scratch cleanup).

## Final joined M3 QA — 2026-10-07

- Actual fmt and offline all-target Clippy `-D warnings` passed. Full offline
  tests first failed three M3 cases (retry HTTP503, search connectivity, timeout
  diagnostic); serial M3 rerun passed all 10. Default-parallel full rerun passed
  **362 executions / 189 distinct tests**, zero failed/ignored. Flakiness remains
  unresolved; logs: `.tmp/m3-qa/final-test{,-repeat}.log`.
- Fresh live smoke without the send-dimensions workaround passed: 30 files/six
  languages, initial 60/0/0, unchanged 0/0/0 (catalog/graph hashes and mtimes
  unchanged), edit/delete 0/2/2 retaining 60, prune 0/0/2 leaving 58, five reranked
  results. Changed prefix/model apply now rejects explicitly. Evidence:
  `.tmp/m3-qa/final/summary.json`.
- **Open defect:** `search --config` through a local HTTPS forwarding proxy
  rejects untrusted TLS correctly; custom CA and insecure mode reach embedding
  and Qdrant with isolated credentials, but CE reranking fails TLS in both modes
  before reaching the proxy. End-to-end shared TLS acceptance is NOT passed.
  Reproducer `.tmp/m3-qa/final-tls.mjs`; evidence `final-tls/auth-tls.json`.
- Both owned collections `zz_m3_6419c0f66fb3` and `zz_m3_569bc3de3616` deleted
  and verified HTTP404. Existing collections untouched; no service restarts,
  Python execution, Rust edits or commits by QA.
- Prior Pier dry-run evidence retained, not rerun: 16,532 items, 2,669 dedicated
  files; added82/changed8225/deleted32556/unchanged8225 against49006 points.
  Request-dimensions/profile/search changes do not change scanner/content diff.
  Independent Python wire oracle and exact tokenizer remain open. The user did
  not require an 80-query retrieval evaluation; scratch search is the QA scope.

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

## M3 — 2026-10-07

Core end-to-end implementation and joined independent scratch-service QA are
available; **full SPEC acceptance is not complete**. No commits were made.
Implementation made no real-service writes; QA mutated only owned scratch collections.

`index` now scans, writes catalog and an empty JSONL graph, compares Qdrant and
defaults to dry-run. `--apply` requires a collection explicitly on the command
line even when config/env supplies one. Missing collections are created with the
first embedding's size and Cosine distance. Bounded embedding workers (default 2,
range 1..32), bounded batches, three transient attempts with 100/200ms backoff,
request timeouts, stderr progress, dimension/index validation and waited Qdrant
upserts/deletes are implemented. Prune requires `--apply --prune`; deletion counts
are printed first. Unchanged runs issue only collection/scroll reads and preserve
catalog/graph contents and mtimes. Lock: `<catalog>.lock`, released on ordinary
success/error; a crashed process can leave a stale lock requiring manual checking.

Credentials use sensitive headers and redacted Debug values; Qdrant gets api-key
and optional bearer, the embedder only its bearer. TLS is verified by default,
additional PEM CA bundles are supported, insecure mode warns and redirects are
limited to the same origin. Transport/status errors do not echo URLs, response
bodies or credentials. Index options use CLI > CODE_DIVER env > config > defaults;
QDRANT_API_KEY, EMBEDDING_API_KEY, SSL_CERT_FILE and configured api_key_env aliases
are supported. YAML service block mappings and TOML embedding/storage/indexing
sections are read; root/catalog/graph_path/CA paths resolve relative to config,
with ~/ expansion. Scanner behavior is unchanged.

The removed hard-coded IntelliJ collection is replaced by no default throughout
the crate. Legacy `--index-update` remains read-only; its `--apply` now fails with
a migration hint to the safe `index --apply --collection` surface, rather than
retaining implicit deletion. Search ranking was not changed.

Embedding request JSON follows the Python float-array body, document prefix and
two truncation stages. Fixture provenance is honest: the synthetic request was
manually transcribed from the Python functions, not captured by running Python.
No cached Qwen tokenizer was integrated; Rust implements the character fallback
`min(max_input_chars, max(1, max_input_tokens-margin)*3)` at both stages (margin
default 32). At defaults the final cap is **1440 Unicode characters**, not 2000.
`--audit-embed-text` reports item/total/max character counts and the token budget,
explicitly marking estimates as non-exact. Exact tokenizer boundary parity is
not claimed, and dense code may still exceed a server token window.

Validation run from this worktree (offline Cargo; loopback mocks only):

```sh
cargo fmt --manifest-path native/code_diver_search_bin/Cargo.toml
cargo clippy --offline --manifest-path native/code_diver_search_bin/Cargo.toml --all-targets -- -D warnings
cargo test --offline --manifest-path native/code_diver_search_bin/Cargo.toml --quiet
git diff --check
```

Post-QA integration counts: **173 unit tests per binary + 16 integrations = 189 distinct tests,
362 executions**, zero failures or ignored tests on the final run. The original 4 CLI tests cover dry
run/create/upsert/auth/503 retry, unchanged/edit/delete +/- prune, dimensions/401
sanitization, bounded timeout and 300 items in 128/128/44 point batches. Nine new
unit tests cover body parity, Unicode/prefix budgets, response validation, lock,
config/path types, redaction/CA rejection and cross-origin credential isolation.
The apply-without-collection test was observed failing before implementation.
Concurrency initially exposed a mock idle-connection bug; the mock was fixed to
handle connections concurrently and the complete suite rerun successfully.
Two additional regressions first failed before the fix: changed embedding model
silently succeeded, and default requests sent optional dimensions. Both now pass.
One full correction run had an intermittent incremental mock transport failure;
targeted backtrace rerun and the subsequent full suite passed without weakened tests.
Its root cause remains unconfirmed.

### Joined independent QA evidence

Source: `.tmp/m3-qa/REPORT.md` and its referenced artifacts; these are QA results,
not implementation-agent reexecution. QA's baseline passed 182 distinct tests /
354 executions. Thirty synthetic files across six languages produced initial
60/0/0, unchanged 0/0/0, edit/delete without prune 0/2/2, and prune 0/0/2.
There were 58 final points and five cross-encoder-reranked scratch search results.
All four owned scratch collections were confirmed HTTP 404 after cleanup.
TLS verified: default untrusted leaf rejected, explicit insecure warned/succeeded,
and a proper signed leaf with explicit CA bundle succeeded.
Pier read-only scan produced 16,532 items against 49,006 existing points:
82 added, 8,225 changed, 32,556 deleted, 8,225 unchanged. This is not permission
to apply/prune Pier and not a retrieval/catalog parity proof.

### Profile safety correction

`<catalog>.embedding-profile.json` stores versioned non-secret preparation settings,
root, endpoints, collection, provider/model, document prefix, dimensions policy and
character/token budgets. Apply to nonempty collections requires an identical
sidecar and matching live provider/model metadata; otherwise it fails before any
remote writes with an explicit new-collection/new-catalog migration instruction.
Dry-run warns that content counts do not establish embedding compatibility.
The sidecar is persisted before initial writes to allow partial-run resumption;
missing/corrupt sidecars are not silently adopted. Point payload shape is unchanged.
Optional request dimensions now default off, matching Python's supported explicit
`send_dimensions=false` mode; supplied dimensions still validate returned vectors.
Collection vector size still comes from the first successful embedding.

### Remaining M3 acceptance / QA handoff

- QA joined before this correction. QA retains `.tmp` ownership. Correction
  validation used loopback mocks only; existing collections remain untouched.
- Scratch search suffices for the requested smoke; no 80-query run was requested
  for this correction and no Hit@k measurement is claimed.
- YAML is still a scoped reader, not a complete YAML parser: anchors, multiline
  strings, inline service mappings and nested service values are unsupported.
  Scanner unknown keys retain M1 fail-fast behavior; embedding/indexing unknown
  scalar keys warn. Search and MCP now share service config/env/auth/TLS settings;
  doctor and legacy dry-run retain their old configuration surface. Graph remains
  empty; production graph weight is 0.0.
- Content diff remains incremental; incompatible/unverified embedding profiles
  now fail on apply instead of silently returning 0/0/0. Migration requires a new
  collection and catalog; this is not an in-place forced-reembedding command.
  Full catalog retention and non-atomic catalog file replacement remain existing
  scalability/durability limitations. Exact Qwen counts remain open; recognized
  context-overflow HTTP 400 splits batches into individual inputs and allows two
  character-halving retries per item. Ordinary 4xx errors fail without retry.
- Exact audit item-would-differ counts require an independent tokenizer/request
  oracle; audit explicitly prints `would_differ_from_python=unknown`, not zero.
  Repository filename search found only the existing manual request fixture;
  independently recorded Python request parity remains unmet. No Python was run.
- Catalog-adjacent locks do not serialize separate catalogs aimed at
  the same collection; the specified catalog lock was intentionally used.

### Shared search integration correction

Search (including MCP's flattened search settings) accepts `--config` or
`CODE_DIVER_CONFIG`, with CLI > CODE_DIVER env > config > defaults for Qdrant and
embedding URLs/model/query prefix/credentials. Explicit default URLs still win
over config. Catalog/graph/config CA paths resolve relative to configuration.
Service URLs reject inline credentials/query/fragment. Separate verified-TLS
clients prevent Qdrant/embedder credentials leaking to each other or the CE.
Query embedding sends the configured model and float encoding, applies the query
prefix before the same estimated character budget, and caches by prepared query,
URL and configured model. Search ranking and CE query text are unchanged.

Index and search share bounded overflow handling: retry only recognized context
HTTP 400 bodies (never log bodies), split batches, then shrink each failed item
at most twice. Python's split/retry structure is preserved, but halving Unicode
characters is not exact tokenizer/budget parity. Tests first reproduced missing
overflow retries; success, exhaustion/no-upsert/redaction now pass.

Audit adds `estimated_threshold_candidates`: the number of stage-one prepared
items whose prefix-inclusive characters exceed `(max_input_tokens-margin)*3`
(effective token budget at least one). This is a measurable heuristic candidate
count, not an exact Python would-differ count. Repository asset search found no
tokenizer JSON; no new tokenizer dependencies/assets were fetched. Only the manual
request fixture was located; the independent Python recording requirement remains
unmet under the no-Python-execution constraint.

Final QA repeat: rerun the Cargo commands above, then fresh owned scratch index
initial/unchanged/edit/delete/prune/search and the existing TLS smoke using shared
search `--config`. Confirm changed model/prefix fail migration before writes and
all scratch collections are cleaned to 404. Never apply/prune existing Pier.