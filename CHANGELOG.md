# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Promoted H-66b to the new IntelliJ champion.** The default configuration for IntelliJ Community is now `configs/intellij/intellij-h66b-champion.yml`. This flip favors the best-measured WHERE arm (+0.073 recall / +0.078 MRR) over the strict 1065 recall gate. While a slight regression on 1065 recall is accepted (-0.0117), the configuration improves hit@1 (+0.0113) and achieves the best-on-record performance for the workflow bucket (0.8027). H-46 remains available as an archived reference.

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

- **H-66b (`configs/intellij/intellij-h66b-champion.yml`) was promoted to the new IntelliJ champion.** This flips the default to the best-measured WHERE arm (+0.073 recall / +0.078 MRR); a regression on the 1065 gate (-0.0117 recall) was explicitly accepted in exchange for improved hit@1 (+0.0113) and workflow bucket performance (0.8027). H-46 (`configs/intellij/intellij-h46-preserve-top.yml`) remains an archived reference.
- **H-77 seed score parity was promoted into the IntelliJ champion.** `graph_file_search.seed_score_parity` (new option, default `false`, so every other configuration stays bit-identical) is now enabled in `configs/intellij/intellij-h66b-champion.yml`. `GraphFileRetrievalStrategy._seed_scores` used to rebuild a candidate's score from two independent sources, so a file that reached the pool through the vector lane but missed the lexical seed top-280 kept `lexical = path = symbol = 0.0` structurally — by absence, not by lack of a match — capping it at `vector_weight` alone. Those candidates are now rescored with the same `HybridCandidateScorer` (same query model, same shared profile cache, no extra tokenization). Measured: WHERE-79 recall@10 0.5757 -> 0.6120, hit@10 51 -> 54/79, ndcg@10 0.4005 -> 0.4095; the 1065 gate scores recall@10 0.8353 (archived champion ~0.8175); a same-sitting 150-case mechanical guard slice moves 0.7977 -> 0.8381 with every bucket up (config +0.0680, path +0.0200, symbol +0.0334). Accepted regressions: WHERE-79 hit@1 20 -> 18 and MRR@10 -0.0029. `configs/intellij/intellij-h77-seed-parity.yml` is kept as the documented arm.
- **`cross_encoder_rerank.preserve_top_depth` (default `1`, i.e. inert)** widens `preserve_top_candidate` from base rank 1 to the first *N* base candidates. Measured on WHERE-79 as a no-op at depth 2/3, so it is enabled in no champion; it stays available for future arms.
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
