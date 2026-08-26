# H3 Where Listwise Replay

## Scope

- Add a standalone Python 3.11 replay harness for the IntelliJ where-only dump.
- Normalize both the frozen `id/query/expected` dataset and the richer candidate dump schema.
- Provide deterministic baseline and gold-pool dry-run controls, plus OpenAI-compatible listwise ranking.

## Design

- `Candidate` and `DumpRecord` are frozen, slotted dataclasses.
- Frozen records without candidates synthesize expected paths as score-zero, empty-snippet candidates.
- Metrics are pure macro averages with explicit empty-gold handling and support multiple gold paths.
- Model output is restricted to validated candidate indices; duplicates are removed and omitted indices are appended in source order.
- The CLI emits one JSON result on stdout, diagnostics on stderr, and refuses existing `--json-out` files.

## Validation

- Unit tests cover schemas, metrics, prompt leakage, parsing, and fake-client control flow.
- Targeted pytest and Ruff checks should be run after implementation.
