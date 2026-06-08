# Architecture & Code Review - 2026-06-08

Scope: 376 Python files / about 41k LOC, 79 test files.

## Verdict

The codebase is structurally strong, but two concentrated hotspots keep it from
being clean enough for long-running research:

- experiment/hypothesis scaffolding is fused into production paths;
- `src/code_diver/cli.py` is a god-module that owns parsing, rendering, runtime
  bootstrap, hardcoded profiles, command handlers, and experiment execution.

The architecture is otherwise healthy: capability-oriented packages, clean
composition through `AppConfig`, real factories, and no broad hygiene rot.

## What To Preserve

- Top-level package names describe product capabilities: `strategies`,
  `providers`, `graph`, `inspection`, `answering`, `explanation`.
- Config/settings layers do not import upward into service/agent/CLI layers.
- `AppConfig` remains a composition root, not a god object.
- Dispatch factories are mostly open for extension and avoid large if/elif
  swamps.
- General hygiene is high: no TODO/FIXME/HACK, no commented-out implementation
  blocks, no debugger breakpoints, no bare `except:`.

## Critical Findings

### C1 - Hypothesis Scaffolding Is In Production Paths

Examples:

- `src/code_diver/cli.py::apply_builtin_h5()` injects frozen tuning weights and
  generation defaults.
- `DirectSearchOrchestrator` and prompt construction infer behavior from
  hypothesis-name substrings such as `monotonic`, `adaptive`, `agentic`, and
  `deep`.
- `H3SearchToolHandler` is exposed as a first-class tool even though the name is
  a historical hypothesis label rather than a product capability.

Risk: eval validity. A renamed hypothesis can silently change behavior, and the
CLI default can become an unlabeled experiment.

Recommended fix:

- promote hypothesis behavior to explicit config data;
- replace substring dispatch with capability flags;
- rename `H3SearchToolHandler` to a capability name such as
  `ManifestUnionSearchHandler`;
- delete dead builtin profile helpers after characterization tests.

### C2 - `cli.py` Is Too Large

`src/code_diver/cli.py` is close to 3k LOC and mixes responsibilities:

- argparse construction;
- Rich rendering;
- runtime bootstrap;
- built-in profile mutation;
- command handlers;
- scanner-mode dispatch;
- experiment/eval execution.

Recommended fix:

- split parser setup from command execution;
- move command handlers under `src/code_diver/cli_commands/`;
- move rendering-specific helpers under `src/code_diver/ui/`;
- leave `code_diver.cli:main` as the stable package entrypoint.

### C3 - Direct Search Loop Hides A Policy Engine

`DirectSearchOrchestrator.search()` combines:

- round loop;
- JSON retry handling;
- forced-step policy;
- fallback bookkeeping;
- 30+ `_should_force_*`/policy helpers.

Recommended fix:

- extract a `SearchTurnPolicy`;
- keep the orchestrator loop as seed -> execute turns -> finalize.

## Major Findings

- Config parsing repeats defaults/merge behavior across dataclasses, loader, and
  experiment override paths.
- Provider constructors have long repeated argument lists and should move toward
  provider config objects.
- `GenerationProvider` is a `Protocol` while several other provider interfaces
  use ABCs; pick one convention.
- `VectorStore.search_0` over-fetch behavior leaks store-specific filtering into
  the base abstraction.

## Quick Wins Applied

- Ruff fixes for unused imports and f-strings without placeholders.
- `CLICKHOUSE_PASSWORD` can now override the default metrics password when YAML
  does not provide one.
- Two broad `except Exception` fallback paths now log debug traces instead of
  silently swallowing every error.

## Open Decisions

- Whether the public default should be a named config profile instead of
  `apply_builtin_h5()` mutation.
- Whether H3/H5/H7 names should remain in user-facing docs or become historical
  labels only.
- Whether local GraphRAG should be a default strategy or an explicit tool the
  agent calls after high-confidence H7 seeds.
