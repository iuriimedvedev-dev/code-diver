# Rust rewrite decisions

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