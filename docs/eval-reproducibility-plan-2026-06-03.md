# Eval Reproducibility Plan - 2026-06-03

## Scope

This note reviews the current evaluation paths and defines the reproducible open benchmark profile used as the public verification path.

Implementation status: `code-diver evaluate --benchmark ...` now exposes first-class benchmark profiles, including `open-protogen-hash-vector-30`.

The current codebase has three relevant eval paths:

- `code-diver evaluate`: direct retrieval evaluation over a fixed index and dataset.
- `code-diver evaluate-search-tools`: direct LLM/tool-orchestrator evaluation over a fixed index and dataset.
- `scripts/run_postrank_h2_deterministic.py`: deterministic post-rank harness for IntelliJ H2/H3/H4-style candidate generation plus reranking.

## Current Eval Paths

### `evaluate`

Entry point: `src/code_diver/cli.py::cmd_evaluate`.

Flow:

1. Load config.
2. Open the configured vector store.
3. If `--reindex` is passed or the store is missing, run `cmd_index`.
4. Load `args.dataset` or `config.evaluation.dataset` through `DatasetLoader`.
5. Apply plugin query rewriting through `plugin_manager.prepare_query`.
6. Build embedding provider and retrieval strategy.
7. Run `EvaluationService.evaluate(cases, limit, workers=config.evaluation.workers)`.
8. Print JSON as `{ "metrics": ..., "results": ... }` when `--json` is used.

Strengths:

- Good deterministic baseline when using `embedding.provider: hash` and `storage.provider: json`.
- `EvaluationService` records `degraded`, `degraded_cases`, `degraded_case_rate`, failed/success duration splits, confidence intervals, bucket metrics, result-kind metrics, and `failure_details`.
- Parallel evaluation now records per-case failures instead of discarding all completed results.
- Supports `glob:` expected labels in both item-level and file-level matching.

Reproducibility gaps:

- JSON output does not include a full run manifest: git SHA, dirty status, command, config hash, dataset hash, corpus hash, Python version, dependency lock hash, host info, and index artifact hash.
- `run_id` is not emitted by `evaluate`.
- Config and dataset are referenced by path but not copied/snapshotted into the report.
- The target corpus version is external to the output.
- Cloud model/provider strategies are not bit-reproducible even with temperature 0.

### `evaluate-search-tools`

Entry point: `src/code_diver/cli.py::cmd_evaluate_search_tools`.

Flow:

1. Load dataset.
2. Create a random `run_id`.
3. For each selected experiment hypothesis:
   - apply `config_for_search_hypothesis`;
   - resolve allowed tools;
   - create generation provider;
   - optionally create rerank generation provider;
   - optionally create search/vector handlers and H3 search handler;
   - create `DirectSearchOrchestrator`;
   - run each case sequentially;
   - merge usage and evaluate retrieved paths with `direct_search_eval_result`.
4. Emit `{ "run_id": ..., "results": [...] }` with per-hypothesis metrics, usage, log path, errors, and optional details.

Strengths:

- Fixed index, fixed dataset, and fixed allowed tool set per hypothesis.
- Emits direct-agent transcripts under `.code-diver/traces`.
- Captures token usage, model names, costs, tool calls, and top-level errors.

Reproducibility gaps:

- Case loop is sequential and unseeded, but model/tool behavior can still vary.
- Metrics do not currently carry a first-class `degraded` flag from orchestrator usage in the same way `EvaluationService` does; error counts are present, but degraded should be explicit in metrics and report tables.
- Logs are schema-compatible enough for humans, but not a stable benchmark artifact contract.
- Without `--details`, final outputs may not contain enough retrieved-order data to rescore after dataset-label changes.

### Deterministic Postrank Runner

Entry point: `scripts/run_postrank_h2_deterministic.py`.

Flow:

1. Load config and dataset.
2. Optionally truncate with `--cases`.
3. Select hypotheses by name.
4. Classify hypothesis into scenario:
   - Branch A: locator + outline/symbols/rg probes + rerank.
   - Branch B: locator + ephemeral candidate-file index + rerank.
   - Branch C: union of retrieval profiles + probes + identifier aliases + rerank.
   - Branch D: query variants + union + probes + aliases + rerank.
5. Write partial JSON every `--progress-every`.
6. Write final JSON and optional HTML report.

Strengths:

- Best current diagnostics: `locator_rank`, `candidate_rank`, `rerank_rank`, source attribution, top locator/candidate/reranked files, tool counters, alias/union counts, rerank errors.
- Supports fixed `--run-id`.
- Captures partial progress for long runs.
- Separates candidate coverage failures from reranker demotions.

Reproducibility gaps:

- Name says deterministic, but LLM reranking and LLM query planning are not bit-deterministic.
- Defaults can change silently across code revisions; every published run must include explicit CLI args.
- Final JSON does not snapshot the full config, dataset hash, target repo hash, model revision, dependency lock hash, or command.
- The report builder normalizes multiple eval JSON shapes, but the benchmark artifact schema is not versioned.

## Proposed Open Reproducible Benchmark Profile

Use one public, dependency-light baseline profile as the CI and reproducibility anchor:

**Profile name:** `open-protogen-hash-vector-30`

Purpose:

- Verify that indexing, retrieval, metric computation, dataset loading, tracing, and report generation are reproducible without cloud APIs or local model servers.
- Provide a one-command benchmark that a person can run before trusting any expensive IntelliJ/model-rerank result.

Current runnable command, assuming the target corpus is checked out at `../protogen`:

```bash
mkdir -p .code-diver/reports/open-repro && \
uv run code-diver --config configs/protogen-baseline.yml evaluate \
  --benchmark open-protogen-hash-vector-30 \
  --limit 10 \
  --details \
  --json \
  --reindex \
  | tee .code-diver/reports/open-repro/protogen-hash-vector-30.json
```

Why this profile:

- `configs/protogen-baseline.yml` uses `storage.provider: json` and `embedding.provider: hash`.
- It does not require Qdrant, ClickHouse, Gemini, OpenAI, Vertex, vLLM, llama.cpp, or any API key.
- `datasets/protogen_eval_30.jsonl` is small enough for CI and local preflight.
- Hash embeddings are not a quality claim, but they are useful as a deterministic harness check.

Validation run from this pass:

| Metric | Value |
| --- | ---: |
| Cases | 30 |
| Hit@1 | 0.000 |
| Hit@3 | 0.033 |
| Hit@5 | 0.067 |
| Hit@10 | 0.133 |
| Recall@10 | 0.133 |
| Precision@10 | 0.020 |
| File Recall@10 | 0.117 |
| nDCG@10 | 0.056 |
| Mean ms | 227.9 |
| Degraded cases | 0 |

These low quality numbers are acceptable for the profile's purpose. It proves the benchmark pipeline is runnable and deterministic without external services; it is not the target search-quality setup.

Open-profile requirement:

- The target corpus must be version-pinned and obtainable by anyone. The current config points to `../protogen`; that is acceptable only if the benchmark release documents a public source URL and exact commit or ships a source tarball with a checksum.
- If `protogen` cannot be made public, this profile should be replaced with a small in-repo fixture corpus plus an in-repo eval set. The important part is that the benchmark target is not a private sibling checkout.

The IntelliJ answer-set benchmark should remain a separate `internal/stress` profile unless the exact IntelliJ checkout, dataset governance, and answer-set versioning are published with the run. Its current value is quality research; it is not the minimal reproducibility anchor.

## Required Artifacts

Artifacts that should be versioned in the repo:

- Benchmark config: YAML profile used for the run.
- Dataset JSONL.
- Dataset schema version and validation policy.
- Metric schema version.
- Report schema version.
- Scripts needed to run and render the benchmark.
- Dependency lock file: `uv.lock`.
- CI workflow for the deterministic open profile.

Artifacts that may be downloaded or generated, but must be pinned:

- Target corpus source checkout or tarball.
- Exact target corpus commit SHA or content checksum.
- Model weights for local model benchmarks, including provider, model id, quantization, revision, and checksum where available.
- Runtime services for non-baseline profiles, such as Qdrant, llama.cpp, vLLM, or ClickHouse, with image tags/digests.

Artifacts that should be generated per run and kept with the report:

- `run.json`: metrics plus per-case results.
- `run-manifest.json`: full reproducibility manifest.
- `config.effective.yml`: resolved config after hypothesis overrides.
- `dataset.sha256`.
- `corpus-manifest.json`: target repo URL/path, commit, dirty status, file count, and source checksum strategy.
- `index-manifest.json`: index artifact path, item count, graph artifact path, embedding provider, dimensions, and artifact hash.
- `trace.jsonl`: retrieval/rerank/tool trace if enabled.
- `report.html`: human-readable report.
- `stderr/stdout.log`: command output.

## Run Manifest Contract

Every published benchmark run should include:

- `benchmark_profile`: stable name, for example `open-protogen-hash-vector-30`.
- `benchmark_schema_version`.
- `command`: exact command line.
- `cwd`.
- `code_diver_git_sha`.
- `code_diver_git_dirty`: boolean plus changed-file list.
- `python_version`.
- `platform`: OS, architecture, CPU/GPU summary if relevant.
- `uv_lock_sha256`.
- `config_path` and `config_sha256`.
- `effective_config_sha256`.
- `dataset_path`, `dataset_sha256`, row count.
- `target_corpus`: URL, commit SHA, dirty status, file count.
- `index_artifacts`: paths, item counts, graph item/edge counts, hashes.
- `retrieval_strategy`.
- `embedding`: provider, model, dimensions, batch size, worker count, model revision/checksum when applicable.
- `generation`: provider, model, fallback models, temperature, thinking budget, timeout, API version.
- `reranker`: provider/model/candidate limit/mode, or `none`.
- `seed`: integer when code supports one; otherwise explicit `null` plus `determinism_class`.
- `run_id`: user-settable, not only random.
- `metrics`: aggregate metrics with confidence intervals.
- `invalid_cases`: count and IDs excluded before run validation.
- `degraded_cases`: count and IDs counted as runtime failures/degraded outputs.
- `case_count_planned`, `case_count_valid`, `case_count_scored`.

Suggested determinism classes:

- `bit_reproducible`: hash embeddings, JSON store, no LLM, single-thread-safe deterministic path.
- `statistically_reproducible`: local model or provider with fixed model revision and deterministic settings, but not guaranteed bit-identical.
- `non_reproducible_cloud`: hosted model API where provider can change weights/serving behavior.

## Seed And Version Policy

The current baseline does not expose a global seed. For reproducible reporting:

- Deterministic profiles should avoid randomness entirely.
- If a code path uses randomness, expose and record a seed before it is allowed into a benchmark profile.
- LLM profiles must record `temperature`, model id, API version, fallback model list, timeout, retry policy, and whether fallbacks were used.
- Retried/fallback model calls must mark the affected case as degraded unless the benchmark profile explicitly defines retry as part of the method.
- Cloud model names are not enough. Reports must state that exact reruns are not guaranteed unless the provider exposes immutable model versions.

## Metrics Policy

Primary metrics for file-location benchmarks:

- `file_hit_rate@1`
- `file_hit_rate@3`
- `file_hit_rate@5`
- `file_hit_rate@10`
- `file_mrr@10`
- `file_recall@10`
- `ndcg@10`
- `map@10`
- `search_duration_ms_mean`
- `search_duration_ms_p95`
- `degraded_case_rate`

Secondary metrics:

- item-level `hit_rate@k`, useful when chunks/symbols are first-class targets;
- `precision@10`, useful for broad answer sets;
- token/cost counters for LLM profiles;
- candidate coverage diagnostics for postrank profiles.

For file-locator claims, headline file-level metrics should be reported before item-level metrics. Item-level `hit_rate@3/@5` can understate or distort file-level success when multiple chunks from the same file appear early.

## Invalid Vs Degraded

Use strict definitions:

- **Invalid case:** cannot be evaluated before the run starts because the row or labels are malformed. Examples: duplicate ID, empty query, empty expected list, missing exact expected path, invalid `glob:` that matches no files, glob over threshold without waiver.
- **Degraded case:** valid case where runtime behavior failed or fell back. Examples: search exception, tool exception, invalid model JSON fallback, model timeout, fallback model used, partial candidate-generation failure, rerank parse failure.

Rules:

- Invalid cases are excluded only by a pre-run validator, before seeing retrieval results.
- Invalid case IDs and reasons must be listed.
- A benchmark with invalid cases should fail CI unless the profile has a checked-in waiver file.
- Degraded cases stay in the denominator and count as misses for primary metrics.
- Report both primary metrics including degraded cases and a diagnostic `non_degraded_only` slice. The headline must be the all-valid-cases score.
- Do not rerun only failed/degraded cases and splice them into the original run.

Current gap:

- `EvaluationService` already has strong degraded accounting.
- `evaluate-search-tools` and the deterministic postrank runner carry errors/degraded counters, but should converge on the same manifest fields and denominator policy.

## Anti-Gaming Rules

To avoid result stuffing or accidental benchmark leakage:

1. Freeze the dataset and target corpus before a final run.
2. Never patch expected labels after inspecting a model's misses and then compare the new score to old runs as if it were the same benchmark.
3. Every answer-set change creates a new dataset version and invalidates direct comparison to old metrics unless old runs are rescored from saved per-case retrieved order.
4. Keep a tuning split and a final holdout split. Hyperparameters can move on the tuning split only.
5. Publish all launched hypotheses in a matrix, including failed, invalid, timeout, and degraded rows.
6. Store per-case retrieved order for every final run.
7. Store candidate coverage diagnostics separately from final rerank metrics.
8. Report exact command and dirty git state.
9. Do not hide fallback models, retries, parse failures, or tool errors.
10. CI must run the deterministic open profile, not a cloud model profile.

## CI Recommendation

Add one required CI job for `open-protogen-hash-vector-30` after the target corpus is made public or replaced by an in-repo fixture:

1. Check out `code-diver`.
2. Restore or download the pinned target corpus.
3. Run `uv sync --locked`.
4. Run the one-command benchmark with `--reindex`.
5. Validate the output schema.
6. Assert:
   - no invalid cases;
   - `degraded_cases == 0`;
   - exact row count;
   - metric values within a tight deterministic tolerance;
   - generated index item count equals expected;
   - `config_sha256`, `dataset_sha256`, and target corpus commit match the profile manifest.

For cloud/model quality profiles, CI should only run smoke checks or schema checks. Full cloud quality runs should be scheduled/manual and reported as non-bit-reproducible.

## Implementation Backlog

Recommended follow-up changes, in order:

1. Add a benchmark profile manifest file for `open-protogen-hash-vector-30`.
2. Add a run-manifest writer shared by `evaluate`, `evaluate-search-tools`, and deterministic postrank.
3. Add `--run-id` and `--output` to `evaluate`.
4. Make `evaluate-search-tools` put `degraded`, `degraded_cases`, and degraded reasons into `metrics`.
5. Add pre-run dataset validation as a benchmark gate.
6. Save effective config and per-case retrieved order by default for benchmark profiles.
7. Add a CI job for the open deterministic profile.
8. Version the report/metrics schema.

## Immediate Recommendation

Use this hierarchy for reporting:

1. **Reproducibility anchor:** `open-protogen-hash-vector-30`, deterministic, public, CI-gated.
2. **Internal large-repo stress:** IntelliJ H3 manifest answer-set profile, with strict/no-glob/exact-only rescoring and full run manifest.
3. **Model quality research:** H3 candidates plus rerankers, reported with degraded/fallback/invalid counters and no bit-reproducibility claim for cloud models.
