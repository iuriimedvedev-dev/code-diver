# Architecture Cleanup Plan - 2026-06-08

Goal: remove experiment scaffolding from production paths without changing
measured retrieval behavior by accident.

## Phase 0 - Characterization Gate

Before moving code, pin current behavior with tests:

- default built-in profile application for `evaluate --benchmark`;
- `apply_builtin_h5()` and `apply_builtin_pure_h3()` output configs;
- direct search orchestrator mode selection for current hypothesis names;
- `H3SearchToolHandler` inputs/outputs and trace payload shape;
- CLI command output smoke for `index`, `search -j`, `search/ask`, and
  `evaluate --benchmark sample`.

Exit criteria: tests fail if default profile weights, strategy, or model routing
change unintentionally.

## Phase 1 - Make Hypothesis Behavior Explicit

Introduce explicit config flags, then migrate existing name-based behavior:

- `DirectSearchPolicyConfig.agentic: bool`;
- `DirectSearchPolicyConfig.monotonic: bool`;
- `DirectSearchPolicyConfig.force_rerank: bool`;
- `DirectSearchPolicyConfig.force_ephemeral: bool`;
- `DirectSearchPolicyConfig.candidate_only_after_search: bool`;
- `DirectSearchPolicyConfig.min_candidate_tool_calls: int`.

Replace substring checks:

- `"monotonic" in name`;
- `startswith("agent_")`;
- `"adaptive" / "agentic" / "deep" in name`.

Exit criteria: no production behavior depends on parsing hypothesis names.

## Phase 2 - Rename Capability Tools

Rename historical tool names behind compatibility aliases:

- `H3SearchToolHandler` -> `ManifestUnionSearchHandler`;
- keep `code_diver_h3_search` as a deprecated tool alias for existing configs;
- introduce `code_diver_manifest_search` as the capability name.

Exit criteria: old configs still run, new configs use capability names.

## Phase 3 - Remove Built-In Profile Mutation From CLI

Replace `apply_builtin_h5()` / `apply_builtin_pure_h3()` with named profile data:

- `configs/profiles/h5-local.yml`;
- `configs/profiles/h7-local.yml`;
- `configs/profiles/graph-file-local.yml`.

CLI should resolve profile names and merge config through the same loader path as
ordinary YAML.

Exit criteria: `cli.py` does not contain hardcoded retrieval weights or model
choices.

## Phase 4 - Split CLI Module

Move code while keeping `code_diver.cli:main` stable:

- `src/code_diver/cli/parser.py`;
- `src/code_diver/cli/runtime.py`;
- `src/code_diver/cli/profile_resolver.py`;
- `src/code_diver/cli_commands/index.py`;
- `src/code_diver/cli_commands/search.py`;
- `src/code_diver/cli_commands/evaluate.py`;
- `src/code_diver/cli_commands/research.py`.

Exit criteria: `src/code_diver/cli.py` becomes a thin entrypoint under 250 LOC.

## Phase 5 - Extract Search Policy Engine

Introduce:

- `SearchTurnPolicy`;
- `SearchTurnState`;
- `SearchFallbackPolicy`;
- `SearchModeCapabilities`.

`DirectSearchOrchestrator.search()` should read as:

```text
seed baseline
while policy.continue:
  ask model
  execute tools
  update state
finalize results
```

Exit criteria: policy branches are unit-testable without model/tool execution.

## Phase 6 - Provider Config Objects

Collapse long provider constructors into config objects:

- `GenerationProviderConfig`;
- `EmbeddingProviderConfig`;
- `RerankerProviderConfig`.

Exit criteria: provider factory calls no longer pass 10+ primitive arguments.

## Non-Goals

- Do not change retrieval weights during cleanup.
- Do not change benchmark labels/datasets.
- Do not promote GraphRAG or agentic search as part of this refactor.
- Do not remove historical configs until compatibility aliases exist.
