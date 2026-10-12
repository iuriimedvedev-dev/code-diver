# M1 catalog builder — 2026-10-07

Delegated implementation worker directly edited this worktree under explicit user
authorization; parent remains orchestration-only. No recursive delegation.

Implemented scanner, generic symbols, summaries/manifests (compact and noncompact),
IDs/tokenization, catalog-only CLI and compare, scoped scanner YAML/TOML config,
synthetic template goldens and CLI/edge-case tests. Reviewed prototype defects;
hidden include and noncompact tests failed before fixes.

Validation: fmt and strict all-targets Clippy green; 104 unit tests per binary,
2 integration tests green. Crate-wide mechanical lint/format changes were required.

Pier: reference 16450; config scan 16532 items, 2669 dedicated files. kb/ generic
1242/1242 IDs/content/tokens. Whole generic shared 11116/11116, but 78 extra IDs
from SPEC-required hidden includes; strict compare fails. Explicit Python
enumeration replay gives 16450 items, 2667 dedicated files and exact 11116/11116
generic equality, no extras. Snapshot HEAD b88c2267f7ea2289813ad1695ffa858ec1867707.

Data only in .tmp/m1/, never staged. Preexisting untracked SPEC.md is preserved
and must not be staged. No Python processes, network, services, push or writes
to external repositories.

Open: owner resolves SPEC-versus-oracle hidden behavior conflict; replace scoped YAML reader with
complete parser when dependencies are available; independently review manually
reference-derived synthetic goldens. Parent must join before independent QA.

Commits: d1d4a4d (mechanical crate lint/format cleanup), f1169c3 (M1 implementation
and tests). Documentation is committed separately. Each commit includes the
mandatory developer co-author trailer. Only our scoped files were staged.

## Independent QA corrections

Initial QA: 106 distinct tests, 210 executions. Corrective validation: 108 unit
tests run twice plus 3 integration tests = 111 distinct tests / 219 executions;
fmt --check and strict offline all-targets Clippy pass. Added JSONL schema negative
tests, first-difference output CLI tests for every field, and direct load_config
tests for all supported builder settings. No cached YAML dependency exists;
retain honest subset with unknown keys/unsupported scanner shapes failing fast.

Only synthetic goldens moved to tests/fixtures (2890 bytes incl. README).
Manual derivation remains explicit; existing Pier catalog is independent oracle.
Rebuilt default catalog and reran kb/whole generic comparison: 16532 vs 16450
items, extra 82 items / 41 files (generic 78, dedicated 4). Dedicated files:
Rust 2669, reference 2667. kb 1242/1242 IDs/content/tokens exact; whole generic
11116 shared IDs/content/tokens exact but 11194 built versus 11116 reference,
strict exit 1. No claim of 100% overall ID parity. Enumeration replay is only
supplemental prior measurement, not acceptance. SPEC hidden includes preserved.

Corrective commits: dd25dbc (fixtures), b22e465 (schema/diagnostics), b8f84c6
(config). Documentation commit follows. Parent should join and independently
review corrections; YAML completeness, manual-fixture independence and the hidden
oracle conflict remain explicit gaps. No prohibited operations or external writes.