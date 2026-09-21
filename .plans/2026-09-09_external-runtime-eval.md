# External embedding runtime and evaluator endpoints

- Preserve existing user changes; no services, installs, builds, live queries, Rust edits, or agents.
- Reproduce missing client-only support with targeted tests before implementation.
- Add validated embedding.runtime_mode (managed default, external client-only) in config loading and provider runtime gate. Preserve embedding metadata and prefixes.
- Add validated evaluator CLI endpoints for shared embedding/Qdrant and independent Python/Rust CE. Derive execution, endpoint probes and frozen identity from the same values; retain no-management safety and journal behavior.
- Verify targeted regressions and existing helper/config tests. Document commands, resume semantics and outcomes in the session note.