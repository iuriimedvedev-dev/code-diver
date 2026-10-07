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