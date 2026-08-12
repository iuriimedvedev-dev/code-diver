# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`code-diver` failed to start on any install without the optional Google stack.**
  `providers/gcs_object_uploader.py` imported `requests` at module level, and `requests`
  was never a declared dependency — it was only present transitively through `datasets`.
  Because `providers/__init__.py` eagerly re-exports `VertexBatchTestService`, a base
  install crashed with `ModuleNotFoundError: requests` before `--help` could render. The
  import is now deferred behind the same `ImportError` guard the rest of the optional
  Google stack uses, and `requests`/`google-auth` are declared in the `gemini` extra.
- **Declared Python floor did not match the code.** `requires-python` said `>=3.10`, but
  eight modules under `settings/` use `enum.StrEnum`, which requires 3.11. Installing on
  3.10 resolved successfully and then failed at import. The floor is now `>=3.11`.
- **License metadata contradicted the license file.** `pyproject.toml` declared MIT while
  `LICENSE` contains the GPL-3.0 text. Metadata now declares `GPL-3.0-only` (PEP 639
  `License-Expression`) with `LICENSE` shipped as `License-File`.
- **`dot()` silently scored mismatched vectors.** Cosine scoring zipped the query and
  document vectors without a length check, so an index built with a different embedding
  model than the active query provider produced plausible-but-wrong rankings from the
  truncated prefix instead of failing. It now raises on a dimension mismatch.
- **Probe failures in the H3 search handler were silently swallowed.** Three
  `except Exception: pass` blocks hid systemic faults — a missing `rg` binary made every
  probe fail while the metrics still reported success and recall quietly dropped. Failures
  are now counted and surfaced as a `probeFailures` metric.

### Changed

- **`datasets` and `google-genai` moved out of the required dependency set** into the
  `benchmarks` and `gemini` extras. Both were already lazily imported behind `ImportError`
  guards, so nothing in the base code path needed them. A base install drops from ~314 MB
  to ~94 MB (30 packages) by no longer pulling `pyarrow`, `pandas`, and `numpy`.
  Install extras with `uv sync --extra benchmarks --extra gemini` (or
  `pip install 'code-diver[benchmarks,gemini]'`); the guard messages now name the extra.
- `zip()` calls over sequences with a guaranteed-equal length invariant (tool call/result
  pairs, item/vector pairs) now pass `strict=True`, converting a silent truncation into a
  loud failure.
- The 23 mutable class-level constants are annotated `ClassVar[...]`, and the two
  `subprocess.run` calls that drive the model-fallback loop pass `check=False` explicitly.

### Added

- Packaging metadata for distribution: `authors`, `keywords`, `classifiers`, and
  `[project.urls]`. `uvx twine check` passes on both sdist and wheel.
- A `[tool.ruff]` configuration and a clean lint gate. Every suppressed rule carries an
  inline rationale; deferred rules are tracked in `docs/release-checklist.md`.
- GitHub Actions CI (`.github/workflows/ci.yml`): lint, tests on Python 3.11/3.12 across
  Linux and macOS, a distribution build validated with `twine check`, and a `base-install`
  job that installs the bare wheel and boots the CLI — the job that would have caught the
  undeclared-`requests` bug above.
