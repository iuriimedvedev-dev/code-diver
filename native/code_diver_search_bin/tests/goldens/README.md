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