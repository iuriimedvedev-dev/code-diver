# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-10-07

### M6 distribution and validation

- Rust-only CI runs fmt, Clippy (`-D warnings`) and both crates' tests on Ubuntu
  and macOS; shell mocks exercise acceptance without Python or a real cluster.
- Release jobs package a `code-diver` executable for aarch64/x86_64 macOS and
  Linux (Linux via cross), with `.tar.gz.sha256` files. Publication is tag-gated
  and requires all builds; manual dispatch never publishes.
- Installer defaults to `v0.5.0`; README begins with installation, setup, doctor
  and MCP. Python installation is deprecated; see `docs/DEPRECATION.md`.
- Repeatable isolated acceptance and nine full-sequence/failure mocks added.
  Mock success does not establish real shared-collection acceptance or release
  availability. Four-target builds and publication remain external release gates.

### Added

- POSIX `install.sh` downloads the configured GitHub release for macOS
  arm64/x86_64 or Linux aarch64/x86_64, verifies SHA256 before installing to
  `$HOME/.local/bin`, and runs interactive setup. `INSTALL_DIR` overrides the
  installation directory independently of `CODE_DIVER_HOME`;
  `CODE_DIVER_VERSION` and `CODE_DIVER_REPOSITORY` allow pinned installs.
- Rust release workflow builds and packages all four targets with
  per-archive `.sha256` files; tag builds publish only after every build succeeds.
  Manual builds validate packaging without publishing a release.
- One-page colleague install/setup/doctor/recovery guide and single-binary
  README introduction. No published release or completed runtime acceptance is
  claimed by these distribution changes.

### Changed

- **Rust M5 configuration and health validation implemented.** Query/document
  embedding prefixes honor flags, environment, config, profile and index
  metadata, with an empty legacy fallback; configured Python prefix semantics
  are preserved. Schema-2 metadata supports the actual hyphenated filename and
  ISO/unix timestamps, checks artifact hashes, refuses model/dimension/collection
  mismatches and warns on prefix overrides. `config show` redacts secrets.
  MCP/doctor require reranking by default; CLI search remains optional with
  `--no-require-rerank`, and failures in either CE pass are explicit. Doctor
  reports timed checks/JSON and exits 1 for failures. Long CE requires physical
  batch/ubatch >=4096, preserving manifest-tested parallel settings.
  Final joined fmt/Clippy/tests/build passed (554 test executions); real-service
  doctor runs remain non-green for missing metadata, long CE500 or incompatible
  models. Paired 80-query prefix testing found only one-query Hit@5/10 differences,
  not statistical superiority. Daemon/setup/MCP registration remain **M5b**;
  full evidence and limitations are in `docs/rust-rewrite/STATUS.md`.

- **H-91a (LightGBM meta-ranker) promoted to new champion.** Replaced the hand-tuned `ce_score + hub_prior` additive formula with a learned LambdaRank model (200 trees, 16 features) trained on 856 queries from the 1065-case dataset. WHERE-78: 78.2% → **87.2%** hit@10 (+7 hits), MRR 0.386 → **0.707** (+0.321), hit@1 23% → **63%** (+31). mech150: 88.2% hit@10, MRR 0.817, hit@1 78.2% — all non-regressive. New champion config: `configs/intellij/intellij-h91a-meta-ranker.yml`. Model artifact: `artifacts/ce_meta_ranker/`.

- Hub prior (H-87..H-89): optional fan-in centrality prior for cross-encoder tail re-ordering (`hub_prior_*` settings, default off); new production champion `configs/intellij/intellij-h89a-champion.yml`.

- **Promoted H-83 to the new IntelliJ champion.** Added conditional two-pass cross-encoder reranking to `configs/intellij/intellij-h66b-champion.yml`. This change targets WHERE-79 "truncation victims" by rescoring candidates with a larger document window (2400 chars) if their first-pass score is below 0.3. In the mech150 same-sitting gate, H-83 improved WHERE recall@10 by 2.2% (0.6120 -> 0.6342) while maintaining bit-identical performance on config, path, and symbol buckets.

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
