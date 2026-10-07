# Rust rewrite decisions

## 2026-10-07 — M4 independent runtime measurement

- Keep live QA read-only: existing Qdrant/services untouched, local release
  binary only, external reads limited to Pier `tmp/rust-pier`. READY's main
  checkout model cannot be read; missing-meta warning is verified, not waived.
  Worktree-root inspection and catalog fallback metadata do not establish real
  Pier source ranges. Final user authorization permits scoped logical commits,
  not pushes or committing data/scratch outputs.
- Use available `.tmp/m2c-intellij.jsonl` (135404 rows) with a local empty graph
  for memory stress. Pier collection stays explicit; mixed-catalog results are
  not a retrieval claim. Retain initial missing-graph failure as harness evidence.
- Distinguish latest lazy readiness828.508/20.483ms from catalog loading
  257.454/4077.046ms and first search5180.245/8876.776ms (Pier/IntelliJ).
  Latest Pier readiness exceeds0.5s; do not extrapolate earlier faster runs.
  Sampled postsearch RSS139575296/1753481216 bytes versus pre-interning
  218497024/3014705152: approximately36.1%/41.8% lower, not high-water or a
  50% claim. Pier <1GB requirement met; IntelliJ >1GB remains a limitation.
- Keep exact catalog-wide Arc token interning, lazy BM25 and removed unused
  maps; preserve JSON, case, sequence, duplicates and numeric ranking goldens.
  Candidate-content cloning remains; loading is slower than the baseline.
- Close the exposed-score defect using the existing comparator's score, not
  adapter sorting or changed result IDs. Regenerated long-query checker passes
  unchanged with scores0.2787063419818878/0.25131291151046753/0.23123851418495175.
- Independently rerun fmt check, offline all-target Clippy -D warnings, and
  offline tests:533 executions (175x2 +6/5/82/11/6/1/72), zero failed/ignored.
  Earlier627/629 arithmetic totals are incorrect. Exact live calls/bytes/RSS
  remain ignored `.tmp/m4-qa/`; STATUS reports their latest actual values.
- Conservative byte-based embedding token budget is not exact tokenizer parity;
  complex Python symbol ranges use indentation/decorators, not CPython AST.
  No live meta-ranking or80-query Hit@k claim or new retrieval gate.
- Commit the joined implementation/tests/Cargo files as one compiling group,
  then validation scripts/docs. Splitting intertwined shared types/server/search
  changes would risk broken intermediate commits; leave session/plans untracked.

## 2026-10-07 — Final commit authorization

- Commit the coherent M3 implementation/shared transport with its regressions and
  synthetic fixture, then the acceptance evidence and plan/session handoff.
- Exclude scratch outputs and real data; do not push. Core is done, not full SPEC
  acceptance: token audit remains estimated and the Python fixture remains manual.
- Required Junie co-author trailers override the requested trailer-free format.

## 2026-10-07 — Independent final QA accepted transport correction

- Independent post-join fmt/Clippy/offline tests/build passed:191 distinct,
  364 executions, zero failures/ignored (`.tmp/m3-qa/join-test.log`).
- Real TLS proxy smoke confirms strict rejection, custom-CA/insecure success
  (five results each), actual CE requests, isolated credentials and warnings.
  Close the earlier CE TLS blocker; historical decisions below remain historical.
  Latest `final-tls/auth-tls.json` supersedes its former failing contents;
  `join-tls-transcript.log` records the repeat, earlier transcript retains history.
- Scratch `zz_m3_4532ebf57edf` cleanup verified HTTP404; existing collections
  untouched. Keep prior Pier dry-run counts, not authorization to apply/prune.
- Only exact tokenizer parity and independent Python fixture remain evidence
  gaps; no 80-query gate. No Rust edits or commits by QA.

## 2026-10-07 — Final transport defects corrected

- CE uses shared verified TLS/CA/insecure/redirect policy without service secrets;
  retain the CE 120-second timeout. Loopback HTTPS regression exercises complete
  search, strict rejection, trusted/insecure CE requests and credential isolation.
- Diagnose instead of serializing or weakening M3 tests: macOS accept inherits
  nonblocking mode, so restore blocking streams explicitly with bounded I/O and
  joined handlers. Delayed-header regression fails before the correction.
  Temporary transport diagnostics were removed after identifying incomplete
  responses/resets. Timeout fixture uses realistic 100ms/500ms separation.
- Full validation 191 distinct/364 executions; four-way stress 24 suites/264
  executions passed. Independent live TLS repeat remains QA-owned after join.
  These results supersede the unresolved-defect decisions immediately below;
  no claim of independently recorded Python or exact tokenizer parity.
- An 80-query evaluation is not a user requirement; do not list it as a gate.

## 2026-10-07 — Final joined M3 QA gate

- Retain default-parallel first-run failures as evidence, despite serial M3 and
  subsequent full-suite success (189 distinct / 362 executions). Do not weaken
  tests or claim the intermittent mock/transport root cause is resolved.
- Shared search TLS remains incomplete: embeddings/Qdrant honor custom CA and
  insecure flags; HTTPS CE fails both. Implementation agent must propagate TLS
  policy to the credential-free CE client and add regression coverage. QA does
  not edit Rust. Reproducer/evidence under `.tmp/m3-qa/final-tls*`.
- Live default-dimensions incremental flow and profile fail-fast guards verified;
  both fresh owned collections cleaned and HTTP404 verified. Retain earlier
  Pier dry-run counts without rerunning unaffected catalog diff; never infer
  authorization to apply/prune Pier. No commits authorized to QA.

## 2026-10-07 — M1

- SPEC wins over Python for explicitly included hidden directories and bare
  `X/**` directory includes at any depth. Pier's `.github/**` produces 82 extra
  items; keep strict comparison failure visible rather than silently filtering.
- Generic parity lane follows the actual Python router registry, including
  `.pyi`, `.mts`, `.cts`, `.c++` and `.h++`. Scala currently falls through to
  generic in Python despite the broader JVM description; its dedicated lane
  decision belongs to M2.
- Keep both binary names so existing MCP command paths remain usable. Shared
  source via `compat_main.rs` avoids duplicate target-source warnings.
- Noncompact summaries are supported, not restricted to prototype compact mode.
  Explicit compact-path and stopword flags override compact-budget-derived
  defaults. Manifest symbol-surface mode is implemented for the generic lane.
- `tokenize_content_chars=0` means full content; positive values count Unicode
  code points, not bytes. ASCII camel/acronym tokenization matches the dump script.
- Preserve Python whitespace/splitlines behavior, BOM, lossy text and generic
  regex `\s*` quirks. Preserve package-first-line summary behavior and separate
  summary (24) versus manifest (20) import caps.
- M1 emits only summary/manifest items, with `symbols: []`. Unsupported item
  generation flags set true fail explicitly rather than being silently ignored.
  Unknown scanner keys and wrong-typed inert settings now fail explicitly;
  configuration values are never logged.
- Network prohibition plus the absence of a cached YAML crate forced a scoped
  scanner-section YAML reader. Supported grammar is documented in STATUS;
  anchors/tags/multiline scanner values fail clearly, not silently misparse.
  This is justified temporary debt, not a claim of complete YAML compatibility.
  Corrective offline cache inspection again found no YAML crate. Inline scanner
  maps, duplicate sections and nested scanner values fail rather than defaulting.
  M1 scanner/builder settings are directly covered through `load_config`; full
  application TOML configuration remains beyond M1.
- Golden expected templates are manually reference-derived synthetic data;
  neither Python nor the external prototype was executed. Real parity uses only
  the already-existing catalog, with generated Rust data kept under `.tmp/`.
  Only our synthetic files moved to `tests/fixtures/` as explicitly requested;
  their README states manual derivation, not Python generation.
- Comparator validates all required token fields and symbols as string arrays.
  Diagnostic samples cover missing/extra IDs, first differing content section,
  metadata field and token field; extras remain a strict failure. Whole generic
  shared records match 11116/11116, but overall ID sets do not match (78 extras).
  Enumeration replay is supplemental only, never acceptance evidence replacing
  the required SPEC-compatible default scan.
- Required full-crate fmt/Clippy checks exposed baseline style debt. Apply
  mechanical fixes rather than allow/suppress lints or weaken tests. Existing
  tests cover the touched search helpers and remain green.

## 2026-10-07 — M2a

- Dedicated Go and TS/JS results replace generic symbols only when nonempty;
  empty dedicated results retain generic fallback. Match Python recognizer order
  and shallow extraction quirks rather than introducing AST parsing or broader
  syntax interpretation. Routing covers `.ts/.tsx/.js/.jsx/.mjs/.cjs/.mts/.cts`.
- Scanner defaults intentionally omit `.mjs/.cjs/.mts/.cts`, as Python does;
  explicit includes bypass the suffix filter. Do not expand scanner defaults
  merely because the router supports those suffixes. Preserve SPEC hidden-file
  traversal and its documented whole-catalog extras.
- Pier must use the exact documented config and full-content tokenization, not
  blanket includes or the Knotgate 1000-character override. Both M2a lanes have
  100% ID/content/token/embed500 equality; no unmatched M2a categories remain.
  Remaining shared mismatches are solely the unported Python AST lane.
- Missing Knotgate reference/config blocks comparison. A default scan and mtime
  filtering are supplemental evidence only, never substitute parity. Interpret
  the requested 2026-10-04 cutoff as end of the local day; timestamps cannot prove
  snapshot identity. The earlier 2024 date in planning was incorrect.
- Keep useful manually derived synthetic goldens; remove only the two redundant
  agent-created standalone TS harness source fixtures. Finalization and local
  logical commits are now explicitly authorized; no push or data-output staging.

## 2026-10-07 — M2b

- Python/Rust dedicated symbols replace generic results only when nonempty;
  case-insensitive routing covers `.py/.pyi/.rs`. This milestone ports catalog
  symbol inputs, not structural spans, graphs or complete language semantics.
- Choose the lighter dependency-free Python token/suite parser for offline
  delivery. RustPython and the Python tree-sitter grammar were not available in
  the inspected Cargo source cache. A heavier parser introduces dependency,
  crate-size and build-cost considerations; these are qualitative tradeoffs,
  **not measured size or build-time savings**. No new dependency was added.
- The tolerant Python parser handles logical statements, immediate class parent
  qualification and common decorators. Detected lexical/suite errors return an
  empty dedicated result, but arbitrary `ast.parse` SyntaxErrors are not all
  detected (e.g. invalid argument grammar or balanced invalid expressions).
  Decorator rendering is not full `ast.unparse`: grouping, precedence, complex
  literals/escapes, f-strings, adjacent literals, comprehensions and tuple
  trailing commas can differ. Exact XID validation and Unicode identifier
  normalization are not implemented. Observed Pier equality is not a full AST
  guarantee; retain these limitations as explicit remaining verification.
- Rust intentionally mirrors the reference's ordered, line-prefix regexes:
  restricted visibility, fixed modifier order, shallow impl generics/paths and
  240-character signatures. It does not track multiline comment/string state;
  declaration-looking lines inside them can become symbols. Same-line attributes
  can hide declarations, nested generics/raw identifiers can yield partial names,
  and only the first matching declaration on a line is emitted. Methods remain
  unqualified functions; aliases/modules/imports/constants are not symbol rules.
  These are reference-port limitations, not claims of Rust grammar correctness.
- Separate common-record equality from ID-set equality: Python's 244 shared
  records match all checked fields, but 4 hidden-file extras mean strict lane
  failure. Keep SPEC traversal and expose the difference; do not filter for a
  passing score. The M2a Python mismatches are historical and resolved on the
  M2b shared records, not evidence of remaining shared differences.
- Empty Pier/IntelliJ Rust references cannot demonstrate real Rust parity.
  Manual goldens (21 Rust symbols) and 8 tests per language plus integrations
  validate contracts only; none were generated by executing Python.
- Reference source revision/freshness remains unknown. Nonempty pinned Rust
  evidence, Python snapshot/coverage acceptance and broader parser verification
  remain open alongside M1/M2a acceptance gaps. No all-SPEC-complete claim and
  no commits authorized by this documentation task.

## 2026-10-07 — M2c

- Follow the actual Python registry: `.java/.kt/.kts` use JVM; Scala remains
  generic. C/C++ covers `.c/.cc/.cpp/.cxx/.h/.hh/.hpp/.hxx/.c++/.h++`, all
  case-insensitive. Preserve scanner defaults and empty dedicated-result fallback.
- Port shallow reference recognizers, not language grammars. JVM retains legacy
  symbol fallback only when the strategy is empty; purpose/terms and manifest
  surface follow declaration/doc/supertype rules. Manual goldens establish the
  intended contract, not independently Python-generated evidence.
- Rust regex has no lookahead. C/C++ terminal `(?=\{|$)` is manually rewritten
  as `(?:\{|$)`: consuming the brace is equivalent for this extractor because
  nothing follows the assertion, captures are unchanged and match offsets are
  unused. Tests cover brace/end acceptance and prototype rejection; this is a
  local equivalence, not a general lookahead transformation.
- Keep strict ID failure separate from common-record percentages. JVM content,
  tokens and first500 embedding are below >=99%; C/C++ 0/0 is no coverage.
  Implementation does not imply completed acceptance. Use closest h66b-budget
  config with explicit uncertainty, never claim literal exact historical config.
- Independent stdlib current-rule replay is allowed; importing/executing Python
  code-diver is not. Zero differences across 64569 files and confirmation of all
  8728 mismatches support the current port, not historical-reference identity.
  6296 mismatches show absent old rows; 2432 remain historically unresolved.
  Preserve current rules instead of tailoring them to an unpinned stale oracle.
- Existing whole-catalog retention explains substantial memory pressure:
  46271283 token String headers alone cost 1110510792 bytes; payload floor is
  1.58 GiB and measured RSS 2.73 GiB. Streaming is necessary future work, outside
  M2c scope; no memory acceptance or regression-free claim is made.
- Finalization now authorizes explicit-path logical local commits of current
  session lanes/fixtures, integration/tests and documentation. Preserve the local
  plan, exclude `.tmp/`, build/data artifacts and unrelated user changes; no push.

## 2026-10-07 — M3

- The user-required catalog-adjacent lock overrides the planner's endpoint-lock
  proposal. Canonical parent paths prevent directory-alias duplication. A stale
  lock is never removed automatically; separate catalog paths remain independent.
- All new index writes require an explicit CLI collection, not config/env defaults.
  Prune is a separate opt-in and reports counts first. The unsafe legacy apply
  route is disabled with a migration hint; legacy dry-run stays available.
- Reuse UUIDv5 URL IDs and Python-shaped item/root/provider/model/dimensions
  payloads, but use raw embedding values (Python does not L2-normalize them).
  `wait=true` makes Qdrant point mutations complete before reporting progress.
- Bound concurrent embedding batches in waves, default two workers and 32 inputs
  per batch; mutations stay sequential. This bounds in-flight text/vector memory
  without introducing a new dependency or unbounded task queue. Transport retries
  are limited to three attempts for transport errors, 429 and 5xx, with backoff;
  4xx errors fail fast and errors omit potentially secret server responses.
- Match both Python preparation stages and the prefix-inclusive character cap.
  A real Qwen tokenizer is not integrated. The default fallback caps at 1440
  Unicode characters (512-32 tokens times 3); audit prints measurable character
  counts and labels token estimates honestly. Dense inputs can still overflow;
  exact tokenizer parity is not claimed. Recognized overflow retry is now bounded
  to batch splitting and two Unicode-character-halving retries per failed item.
- A manually reference-derived synthetic request body is used because Python
  execution was forbidden. Its fixture provenance explicitly distinguishes it
  from an independently captured Python request; short-text parity is tested.
- Preserve M1 scoped YAML/scanner behavior; read existing service block mappings
  and TOML for indexing and shared search/MCP service settings. Doctor/legacy
  dry-run are not a completed global settings migration.
  Joined QA now verifies self-signed TLS
  rejection, explicit insecure warning/success and signed leaf/CA bundle success.

### Joined QA corrections

- Prefer fail-fast migration over implicit full-collection reembedding: persist
  a versioned non-secret profile next to the locked catalog before initial writes.
  Nonempty collections require matching sidecar plus live model/provider metadata.
  Missing profile is unverified, never silently inferred from content or metadata
  (prefix/budgets cannot be recovered from Python-shaped payloads). Use a new
  collection and catalog for migration; no new fields are added to point payloads.
- Default optional request dimensions off because the live Qwen provider rejects
  Matryoshka dimensions with HTTP 400. Python supports explicit send_dimensions=false;
  this is a deliberate default difference, not a claim of identical Python defaults.
  Supplied dimensions still validate vectors; create uses the first returned size.
- Audit item-would-differ counts are unknown without an exact independent oracle.
  Keep measurable character counts and explicitly print unknown; do not label
  character heuristics as tokenizer parity. Recorded Rust wire bodies are not
  Python recordings. No independent Python request oracle was located.
- Joined QA: 30 files/six languages; initial60/0/0, unchanged0/0/0,
  edit/delete0/2/2, prune0/0/2, 58 points/five reranked results. Four owned scratch
  collections cleaned to404. Pier read-only:16532 items,49006 existing,
  added82/changed8225/deleted32556/unchanged8225; no approval to mutate Pier.
- Shared search/MCP now uses the same config/env service precedence and isolated
  auth/TLS clients. Query prefix is applied before the estimated cap, and model
  plus prepared query participates in cache invalidation; CE/ranking stay unchanged.
- Overflow HTTP 400 classification is private and narrow; ordinary 4xx fail fast.
  Split batches into single items and permit two shrinking attempts each, matching
  Python's control structure, not its exact tokenizer-based shortened text.
- Audit counts estimated threshold candidates before final fallback truncation.
  This supplies measurable item counts without falsely equating candidates with
  actual Python text differences. No tokenizer assets or independent recording
  were found; exact parity remains unclaimed. No Python or real services executed.