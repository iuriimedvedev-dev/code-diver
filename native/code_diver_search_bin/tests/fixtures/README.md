# Synthetic M1 template goldens

`generic.json` contains four synthetic sources and manually transcribed expected
Python summary/manifest contents (default noncompact settings). No internal source
content and no generated production catalogs are included. Total size is under
4 KB; JSON escaping represents exact content newlines.

Oracle references: `FileSummaryItemBuilder`, `FileManifestItemBuilder` and
`GenericStrategy` in the read-only Python tree. These are reference-derived
template goldens, not outputs from running Python. The task prohibits all Python
reference generation. Existing Pier catalog comparison supplies an independent
real generic-lane parity measurement; see STATUS.md for counts and limitations.

The harness verifies both contents, item names, empty symbols and the ten-field
serialized schema. Separate tests verify SHA1 IDs, camel/acronym tokenization,
content character budgets, scanner edge cases and template caps.

## Runtime helpers

Runtime tests do not execute Python. Cargo builds the test-only `runtime-test-helper` from
`tests/helpers/runtime_helper.rs`; tests copy it as `fake-llama`, `llama-server`,
or `claude` to select daemon fault injection, acceptance HTTP, or host registration.
`tests/helpers/pty.rs` uses the dev-only libc dependency to exercise installer
prompts through a controlling terminal while stdin remains non-TTY.

Run `cargo test` normally, including targeted integration or unit-only daemon runs.
Tests build the harness-free helper on demand and use Cargo's JSON artifact output
to locate its executable in the active target directory and profile. It is not a
binary target, so `cargo install` and production binary builds do not ship it.
`no_python_helpers` statically guards executable Python fixtures and references;
Python source-language extraction fixtures remain inert test data.