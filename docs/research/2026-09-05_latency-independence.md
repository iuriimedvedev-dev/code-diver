# R4 and evaluation independence — executor evidence

Status: branch handoff, **not a joined R1–R4 final report**. Parent must join evidence by case ID before making promotion/quality decisions. No production/champion edits, service operations, CE HTTP calls, dependency installs, or retraining were performed.

## Reproduction and evidence

Working directory: `/Users/iurii.medvedev/Work/code-diver`.

```sh
uv run --no-sync pytest -q tests/test_research_latency_independence.py
uv run --no-sync python scripts/research_latency_independence.py --smoke
uv run --no-sync python scripts/research_latency_independence.py
uv run --no-sync pytest -q tests/test_research_latency_independence.py
uv run --no-sync python scripts/research_latency_independence.py --audit-only
```

Outputs under `artifacts/research/2026-09-05/latency-independence/`:

- `smoke.json`: all five arms completed, 7.126 seconds.
- `results.json`: raw latency samples, scores, process peak RSS, versions, environment, input hashes and initial audit. Benchmark elapsed 154.408 seconds; combined microbench runtime 161.534 seconds, below five minutes.
- `audit.json`: final audit with explicit slice case IDs and updated script/test hashes. Slice support was added after benchmarking; benchmark code was unchanged and not rerun unnecessarily.
- Final unit tests: **6 passed in 0.69 seconds**. Coverage includes normalization versus answer-family distinction, glob/directory filtering, empty sets, deterministic real splitter, invalid fraction, real subprocess timeout/error handling, percentiles and deduplicated slices.

SHA-256 anchors (complete dataset/config/dependency/source hashes are in the JSON `audit.sha256` maps):

| Input | SHA-256 |
|---|---|
| Model manifest | `e74f538ff7ca54036e834ea9ab227244537155ed825d715c97ba9596abfca688` |
| Model text | `8dcadfdc02b050fd35ebafca7f436c822859ff38cfeba4f9bd1203abc90e5010` |
| 1065 answer sets | `30511f63ad15a4466f9dd9066cd7d4b88816385ca63a264c1bf2ef3ad6598962` |
| WHERE-78 | `0d0ac47ce100eebc7e006be209d06cf695f3e26a72f34e56e22ae376fd50a30a` |
| mech150 | `e9e5ae2b55fa875d6c40718b985dc44eadbd7b10899c3024888158328ba58629` |
| Benchmark results | `67970910044d738a3ad382d714e64d17a417b9832a95094353e5daea8f19bf91` |

Corpus/index snapshot hash is **blocked**, not inferred from configuration: no proven indexed-corpus manifest is available and services were not accessed. Lockfile hash is recorded, but is not proof of historical training dependencies.

## Model and provenance

`artifacts/ce_meta_ranker/ranker.json` names `ce_meta_ranker.lgb.txt`, 16 feature names, seed 42, test fraction 0.2, 856 training queries and 209 test queries; feature source is only the basename `ce_meta_features.jsonl`. Text model and loaded Booster confirm 200 trees, 16 features, LambdaRank; saved parameters specify learning rate 0.05, 15 leaves and 16 threads. Historical session notes saying 64 leaves / 0.02 disagree with the artifact and current trainer: prefer artifact evidence.

No training feature dump was located. Manifest lacks dataset hashes, actual train/test IDs, corpus/config snapshots, feature-content hashes or a training execution record. The H-91a champion config claims training on the 1065 dataset, and reconstruction exactly reproduces 856/209; this is strong consistency evidence, **not sufficient provenance proof**.

## LightGBM microbenchmark

Environment: macOS 26.6.2 arm64, 16 logical CPUs, Python 3.12.12, LightGBM 4.7.0, NumPy 2.5.1; `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` unset. Other executor activity was possible; this is not an isolated machine experiment.

No real feature dump exists, so use one fixed contiguous float64 normal matrix, `default_rng(34)`, shape **34 × 16**. Matrix SHA-256: `1339b7e15529949ff3407c7d8fe9141ac6e25d46860c4761c691d1a3868d7050`. Synthetic values are not necessarily semantically valid features: this measures model compute only, **not retrieval quality**.

Each arm ran 20 fresh Python processes, each loading a fresh Booster, timing its first prediction, then 50 warm predictions (1000 warm samples/arm). Thread-arm order was seeded and shuffled each round. Timing uses `perf_counter_ns`; imports and interpreter startup are excluded. No explicit `num_threads` argument for default; other arms pass 1, 2, 4 or 8 only to `predict`. Load is therefore identical code across arms, not a load-thread experiment. OS page cache was not flushed: “cold” means process/model-cold, not disk-cold. Per-process timeout is 10 seconds; first timeout/error disables that arm; global benchmark budget is 270 seconds. No timeouts or errors occurred.

All values below are milliseconds, **p50 / p95**; NumPy linear percentiles.

| Predict threads | Process-cold load (n=20) | First prediction (n=20) | Warm prediction (n=1000) |
|---|---:|---:|---:|
| 1 | 3.717 / 5.063 | 0.328 / 0.350 | 0.119 / 0.154 |
| 2 | 3.824 / 12.959 | 0.282 / 0.323 | 0.083 / 0.152 |
| 4 | 4.063 / 5.224 | 0.258 / 0.405 | 0.064 / 0.182 |
| 8 | 3.733 / 6.837 | 0.272 / 0.656 | 0.077 / 0.297 |
| default | 3.776 / 4.280 | 0.223 / 0.278 | 0.084 / 0.149 |

Maximum absolute score drift against thread 1 is **0.0 for every arm**, with exact repeat identity within each worker. This is numerical identity on one synthetic input, not quality identity. Process peak RSS ranges from 221,216,768 to 229,949,440 bytes across runs, including Python/imported libraries; it is not incremental model memory.

**Verdict:** none of the explicit settings improves observed warm p95 over default. Four threads improves median only; do not accept it under the p95 gate. Small differences are not statistically established; warm samples are clustered within 20 processes and cold p95 has only 20 observations. No production recommendation or end-to-end speedup follows. Production passes Python lists, whereas this benchmark uses a NumPy array, so list conversion and surrounding feature extraction are excluded. Full pipeline warm/cold runs, stage shares, embedder startup attribution and service-warming effects are **blocked/out of this executor's authorized scope**.

## Actual split algorithm and labels

`LtrQuerySplitter` deduplicates/sorts IDs and hashes UTF-8 `"{seed}:{query_id}"` with SHA-256; the first eight bytes interpreted big-endian divided by 2^64 form the bucket. A value below 0.2 is test. It splits by ID, not normalized text, semantic family or expected answer. The trainer checks ID overlap for its internal split, but the optional `--test-features` evaluation does **not** reject overlaps against training IDs.

`CeMetaFeatureCollector` captures candidates keyed by query text, joins them back to evaluation cases, and writes `query_id=case.id`; labels are generated directly from each case's expected paths through `ExpectedPathMatcher`. That matcher accepts `glob:` patterns and exact paths **or directory prefixes**. This establishes how this checkout generates labels, not which historical cases generated the saved model. Text-identical cases with different IDs can therefore be split across train/test.

Definitions used here:

- Query family proxy: NFKC + casefold + Unicode word tokens joined by spaces. It detects lexical duplicates, **not semantic paraphrases**.
- Answer-set family: identical nonempty sets of syntactically exact file labels. “Any answer” means at least one shared exact label; these are direct overlaps, not transitive family components.
- `full`: all expected labels; `no_glob`: remove `glob:` entries; `exact_only`: additionally require a filename-extension suffix and reject wildcard syntax. This is a syntactic file proxy, not filesystem verification. No glob expansion or directory-to-file resolution was performed.

| Dataset | Rows / unique IDs | Unique normalized queries | Duplicate groups / excess rows | Full / no-glob / exact label entries | Reconstructed train / test |
|---|---:|---:|---:|---:|---:|
| 1065 | 1065 / 1065 | 1037 | 10 / 28 | 1349 / 1277 / 1277 | 856 / 209 |
| WHERE | 78 / 78 | 78 | 0 / 0 | 115 / 115 / 115 | 63 / 15 |
| mech150 | 229 / 229 | 222 | 5 / 7 | 339 / 327 / 327 | 192 / 37 |

Every case retains at least one label under every policy. Counts of test cases overlapping their reconstructed training half:

| Dataset | Same ID | Same normalized query | Same answer set | Any shared exact answer |
|---|---:|---:|---:|---:|
| 1065 | 0 | 3 | 113 | 113 |
| WHERE | 0 | 0 | 0 | 0 |
| mech150 | 0 | 0 | 16 | 16 |

The three overlapping normalized-query test IDs are `config-platform-dvcs-impl-shared-module-content.yaml`, `config-platform-execution.dashboard-frontend-module-content.yaml`, and `config-platform-execution.serviceview-frontend-module-content.yaml`.

For the 209-case test half: 113 cases (54.1%) have query/answer-family overlap risk; 96 have no such direct overlap before deduplication. Removing training-query overlap and retaining the first test row per normalized query leaves 205 cases; also removing answer overlap leaves **95**. Corresponding deduplicated query-novel / query-and-answer-novel counts are 15/15 for WHERE and 37/21 for mech150's separate reconstructions. `audit.json` preserves slice and split IDs; no slice quality scores are fabricated without per-case retrieval results.

## Cross-dataset overlap and independence verdict

Counts below refer to rows in the right-hand dataset:

| Left → right | Same ID | Same normalized query | Same answer set | Any exact answer |
|---|---:|---:|---:|---:|
| 1065 → WHERE | 78 | 78 | 77 | 78 |
| 1065 → mech150 | 229 | 229 | 229 | 229 |
| WHERE → mech150 | 78 | 78 | 77 | 78 |

Thus WHERE is not independent of mech150, and both are wholly included by ID/query in the current 1065 dataset. Answer-set identity is not universal even when IDs/queries match: joining by ID must preserve dataset-specific labels.

**Conditional on the model having been trained from the current 1065 cases with the recorded seed/fraction:** 63/78 WHERE and 192/229 mech150 cases are training IDs. Any exact-answer overlap against that reconstructed training set affects 63/78 WHERE and 208/229 mech150 cases. These counts do not turn an undocumented historical run into proven provenance.

**Verdict:** dataset overlap is demonstrated; query-ID disjointness alone is insufficient for family-independent evaluation. Repeated expected files are an evaluation dependence risk, **not proof of leakage**. The champion model's factual independence remains **unproven/blocked**. Obtain the original feature dump and hashed training/evaluation/corpus manifests, then have the parent join exact case sets and report strict, no-glob, deduplicated and family-novel slices. No retraining or promotion was attempted here.