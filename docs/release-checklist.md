# Release checklist

State as of the release-prep pass. Everything under "Done" is verified locally;
everything under "Open" is deliberately deferred with the reason recorded.

## Verified

- [x] `uv run ruff check src tests` — clean
- [x] `uv run pytest` — 436 passed
- [x] `uv build` + `uvx twine check dist/*` — both artifacts PASSED
- [x] Wheel metadata: `License-Expression: GPL-3.0-only`, `Requires-Python: >=3.11`,
      base requirements limited to 5 packages, `benchmarks`/`gemini` extras declared
- [x] Base wheel installs and `code-diver --help` starts on a clean Python 3.11 venv
      with no optional dependencies present (30 packages, ~94 MB)
- [x] No secrets in tracked files; no `shell=True` / `eval` / `os.system` anywhere

## Open — blocking a public release

- [ ] **Confirm the GPL-3.0 choice is intended.** Metadata now matches the `LICENSE`
      file, but `LICENSE` was never explicitly chosen — verify GPL-3.0 copyleft is what
      you want before publishing, because it is hard to walk back once released.
- [ ] **Add a copyright holder line to `LICENSE`.** The GPL text ships with the FSF
      boilerplate and no `Copyright (C) <year> <name>` attribution.
- [ ] **Decide the distribution target.** Nothing here publishes to PyPI yet; the CI
      `build` job only uploads artifacts. Add a tag-triggered release job with Trusted
      Publishing if PyPI is the goal.

## Open — quality, non-blocking

- [ ] **`src/code_diver/cli.py` is 4301 lines with 138 functions.** It mixes argument
      parsing, ~30 command bodies, provider wiring, and presentation formatting in one
      module. This directly contradicts the project's own SOLID/no-god-object standard.
      Split by seam: `cli/parser.py`, one module per command group, and move the
      `index_*_label` / `render_*` formatting helpers into `ui/`.
- [ ] **36 `BLE001` blind `except Exception` handlers** (`ruff` rule is currently
      ignored). Each needs a per-site decision: narrow the exception, or catch broadly
      and record the failure. The three worst offenders — silent `pass` in the H3 probe
      loop — are already fixed as a pattern to follow.
- [ ] **16 `TRY004` sites** raise `ValueError` where a type check failed and should raise
      `TypeError`. Mechanical, but it changes the exception type callers see, so it wants
      its own commit and a test sweep.
- [ ] **Run `ruff format` as a single isolated commit.** 90 of 379 files would be
      reformatted. Kept out of the release-prep diff on purpose so the substantive
      changes stay reviewable; once done, re-add the `ruff format --check` gate to the
      `lint` CI job.
- [ ] **No static type checking.** There is no mypy or pyright config despite thorough
      annotation coverage. Start with `mypy --ignore-missing-imports` on
      `settings/`, `config/`, and `domain/` (the most stable layers) rather than repo-wide.
- [ ] **No coverage measurement.** 436 tests exist with no idea what they cover. Add
      `pytest-cov` and record the baseline before setting a threshold.
- [ ] **Research scaffolding sits in the shipping CLI.** `apply_builtin_h5`,
      `apply_builtin_pure_h3`, and `agent/h3_search_tool_handler.py` encode
      experiment-hypothesis names in product code. Either rename to describe the
      retrieval behavior, or move behind the `--help-all` research surface.
- [ ] **Document the ClickHouse default credentials.** `Defaults.CLICKHOUSE_PASSWORD`
      is `"code_diver"`. It is env-overridable via `CLICKHOUSE_PASSWORD` and the metrics
      store is a local sidecar, so this is acceptable — but it should be stated in the
      README so nobody exposes that container.

## Release steps

1. Resolve the blocking items above.
2. Move the `[Unreleased]` section of `CHANGELOG.md` under a `[0.1.0]` heading with a date.
3. Verify `version` in `pyproject.toml` matches, then tag: `git tag -a v0.1.0 -m "v0.1.0"`.
4. Confirm CI is green on the tag, then publish the artifacts from the `build` job.
