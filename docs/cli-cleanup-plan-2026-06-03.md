# CLI Cleanup Plan

Date: 2026-06-03

Scope: review plus first cleanup slice. The public CLI should make the assignment flow reproducible and easy to understand:

```bash
code-diver index
code-diver search "where is authentication handled?"
code-diver evaluate
```

Implemented in this pass:

- default `code-diver --help` now shows only `index`, `search`, and `evaluate`;
- advanced inspection/agent/research commands remain callable and are visible via `code-diver --help-all`;
- `evaluate --benchmark ...` exposes reproducible benchmark profiles;
- `evaluate` human output now uses a compact Rich summary table while `--json` remains machine-readable.

## 1. Current CLI Problems

The CLI is functionally rich, but it reads like a research workbench rather than a focused deliverable.

- `code-diver --help` is crowded. The primary commands share the top-level namespace with `index-selected`, `tree`, `grep`, `rg`, `read`, `symbols`, `open`, `chat`, `ask`, `evaluate-indexing`, `evaluate-search-tools`, `experiment`, and `monitor`.
- `src/code_diver/cli.py` owns too much: parser wiring, indexing, search, evaluation, experiment execution, direct agent runs, metrics persistence, trace monitoring, provider construction, graph indexing, and JSON conversion.
- The public naming is inconsistent with the assignment mental model. `evaluate` is the clean benchmark command, but `experiment`, `evaluate-indexing`, and `evaluate-search-tools` are adjacent and look equally official.
- Research commands are useful but unsafe as first impressions. `evaluate-search-tools` and `evaluate-indexing` depend on hypotheses, tool allowlists, model orchestration, traces, and cost-bearing providers. They should not be what a reviewer sees first.
- Output modes are not clearly tiered. `search` has a Rich renderer and `--json`; `evaluate` prints raw metric lines or JSON; `index` prints a short summary plus composition. There is no unified "human summary first, machine JSON when requested" contract.
- Config behavior is powerful but implicit. `--config` can appear before or after subcommands via `normalize_argv`, defaults silently load `code-diver.yml` when present, and missing config falls back to defaults. This is convenient, but the CLI does not surface the active root, store, dataset, strategy, or provider consistently.
- Reproducibility is partially there but not visible enough. The hash-provider e2e test proves `index -> search -> evaluate` can be deterministic, but normal command output does not consistently show config path, root, artifact/store, embedding provider/model, dataset, limit, and strategy.
- Help text does not separate stable commands from internal/research commands. `argparse` supports aliases and hidden help, but the current parser exposes everything equally.
- TUI/readability is halfway done. `SearchRenderer` already uses Rich panels, syntax highlighting, links, and pager support, but the visual style is not organized around a compact result list, stable metadata rows, and readable non-color fallback.

## 2. Target UX

The top-level CLI should present three stable commands and make them boringly reproducible.

### `code-diver index`

Purpose: build or refresh the configured index.

Expected human output:

```text
Code Diver index
root: /path/to/repo
store: .code-diver/index.json
embedding: hash-token-v1, dimensions=256
items: 1284
composition: chunk=1200, symbol=84
graph: disabled
trace: .code-diver/traces/indexing.jsonl
```

Target behavior:

- Always print root, store, embedding provider/model/dimensions, scanner mode, item count, and graph status.
- Keep `--json` for machine-readable output with the same fields.
- Add a clear success/failure footer; avoid burying actionable errors in stack-ish text.
- Prefer deterministic defaults for assignment/demo configs, especially hash embeddings and JSON storage.

### `code-diver search`

Purpose: search an existing index for a natural-language or identifier query.

Expected human output:

```text
Code Diver search
query: where is authentication handled?
strategy: hybrid
limit: 10

1. src/auth/service.py:12-40  score=0.8123  kind=chunk
   def authenticate_user(...)

2. src/auth/routes.py:4-28  score=0.7341  kind=chunk
   router.post("/login", ...)
```

Target behavior:

- If the index is missing, the current actionable error is good: keep "Run `code-diver index` first."
- Show the active strategy and store before results, unless `--json` is used.
- Keep Rich rendering, but use a compact result table plus snippets rather than visually heavy panels for every result.
- Preserve clickable editor links when enabled, but ensure plain terminal output remains readable.
- `--json` should include query, config/store metadata, and result list, not only bare results.

### `code-diver evaluate`

Purpose: run a configured dataset against the configured search strategy.

Expected human output:

```text
Code Diver evaluate
dataset: datasets/sample_eval.jsonl
cases: 100
strategy: hybrid
limit: 10

Hit@1: 0.720
Hit@3: 0.840
Hit@10: 0.910
MRR@10: 0.781
File Recall@10: 0.910
mean_ms: 42.3
```

Target behavior:

- Always show dataset, case count, limit, strategy, workers, provider/model, and whether reindex happened.
- Use stable metric ordering instead of iterating raw dict insertion order.
- `--details` should print misses first or write a details artifact path; long per-case output should not overwhelm the default.
- `--json` should stay the CI contract and include config metadata, metrics, and per-case results.
- `--reindex` should report the index phase as a nested step while keeping JSON stdout clean; the current stderr redirect in JSON mode is the right direction.

## 3. Hiding Research Commands Without Breaking Them

Do not delete research commands. Move them out of the first-screen UX.

Recommended compatibility path:

- Keep existing command names callable for scripts:
  - `index-selected`
  - `tree`
  - `grep`
  - `rg`
  - `read`
  - `symbols`
  - `open`
  - `chat`
  - `ask`
  - `evaluate-indexing`
  - `evaluate-search-tools`
  - `experiment`
  - `monitor`
- Hide them from default help with `argparse.SUPPRESS`, or place them under grouped namespaces:
  - `code-diver inspect tree|grep|rg|read|symbols`
  - `code-diver agent ask|chat`
  - `code-diver research experiment|evaluate-indexing|evaluate-search-tools|index-selected|monitor`
- Add backward-compatible aliases so current commands still work and emit no warning initially.
- Later, add a soft deprecation note only in docs or verbose help, not in normal command output.
- Add `code-diver --help-all` or `code-diver research --help` for advanced users.
- Keep tests for old command names until aliases are explicitly removed.

This gives reviewers the clean assignment surface while preserving the research harness.

## 4. TUI And Gradients, But Readable

The CLI can look polished without becoming noisy.

- Use Rich as the only terminal rendering dependency. It is already in `pyproject.toml`.
- Keep color optional via `ui.color`; honor no-color environments and make monochrome output fully understandable.
- Avoid rainbow gradients for data. Use one restrained accent for the product/header, one success color, one warning/error color, and dim metadata.
- If gradients are used, reserve them for a short header rule or title only. Never use gradients for paths, code, scores, metrics, or errors.
- Make search output scannable:
  - compact rank/path/score/kind line;
  - syntax-highlighted snippet below;
  - no nested card-like panels for every result unless pager mode is active.
- Make evaluation output table-like:
  - fixed metric order;
  - aligned values;
  - optional confidence intervals when present;
  - terse miss summary.
- Provide a clear split between display and data:
  - `--json` means no Rich formatting and no incidental progress on stdout;
  - human mode can show progress, tables, and snippets;
  - stderr is reserved for progress and warnings in JSON mode.
- For long-running `index` and `evaluate`, use readable progress bars only when stdout is a TTY. In CI, print deterministic line events or stay quiet.

## 5. Code Files To Change Later

Primary CLI surface:

- `src/code_diver/cli.py`
  - Split parser construction into public, inspect, agent, and research groups.
  - Add hidden aliases or grouped subcommands.
  - Standardize JSON envelopes for `index`, `search`, and `evaluate`.
  - Move orchestration-heavy command bodies out of this file.
- `src/code_diver/settings/cli_names.py`
  - Add command groups or aliases while preserving existing command names.
  - Add any new option names such as `--help-all`, `--plain`, or `--output`.
- `pyproject.toml`
  - Keep the same `code-diver = "code_diver.cli:main"` entrypoint.
  - No dependency change needed for Rich-based cleanup.

Rendering and UI:

- `src/code_diver/ui/search_renderer.py`
  - Replace per-result heavy panels with compact, readable ranked output.
  - Add plain/CI-friendly mode and a stable header.
- `src/code_diver/ui/search_snippet_builder.py`
  - Keep snippet selection, but support highlighted query terms if rendering layer needs it.
- `src/code_diver/config/ui_config.py`
  - Add display knobs only if needed: density, theme, progress, plain mode.
- `src/code_diver/settings/defaults.py`
  - Add defaults for any new UI/progress/help behavior.

Command services to extract from `cli.py`:

- `src/code_diver/services/indexing_service.py`
  - Already owns index building; expose a result object suitable for CLI output.
- `src/code_diver/services/evaluation_service.py`
  - Already owns core evaluation; add/report stable metric ordering outside CLI.
- `src/code_diver/experiments/experiment_runner.py`
  - Keep research experiment execution behind research commands.
- New later file: `src/code_diver/cli_commands.py` or package `src/code_diver/cli/`
  - Move command handlers out of monolithic `cli.py`.
- New later file: `src/code_diver/ui/evaluation_renderer.py`
  - Human-readable evaluate summary and details/miss rendering.
- New later file: `src/code_diver/ui/index_renderer.py`
  - Human-readable index summary and composition rendering.

Config and reproducibility:

- `src/code_diver/config/config_loader.py`
  - Optionally expose config source path and loaded defaults for command metadata.
- `src/code_diver/config/app_config.py`
  - If needed, carry display-safe run metadata.
- `src/code_diver/store/vector_store_factory.py`
  - If needed, provide a display label or metadata summary rather than duplicating store labels in CLI.

Tests and docs:

- `tests/smoke/test_cli_smoke.py`
  - Update default help expectations to show only `index`, `search`, and `evaluate`.
  - Add `--help-all` or research help coverage.
- `tests/test_cli_hash.py`
  - Keep the deterministic `index -> search -> evaluate` e2e as the assignment contract.
  - Update JSON assertions if output envelopes change.
- `tests/e2e/test_inspection_cli.py`
  - Keep old diagnostic commands covered as backward-compatible aliases.
- `tests/unit/test_cli_helpers.py`
  - Move helper tests if CLI internals are extracted.
- `README.md`
  - Put the three-command assignment flow first.
  - Move research/runtime sections below an "Advanced" heading.

## Recommended Order

1. Keep command behavior unchanged, but hide research commands from default help.
2. Standardize human and JSON output for `index`, `search`, and `evaluate`.
3. Extract research command handlers out of `src/code_diver/cli.py`.
4. Add compact Rich renderers for index/evaluate/search.
5. Update README and smoke/e2e tests around the new public UX.
