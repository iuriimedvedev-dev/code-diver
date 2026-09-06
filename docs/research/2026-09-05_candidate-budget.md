# R3: candidate-budget evidence and offline diagnostic

## Verdict

**Original R3 is BLOCKED, not accepted or disproved:** there is no audited, case-joined H-91a multi-probe pool with deeper CE scores/features and an independently verifiable split. CE34 versus CE60/80 post-rerank recall/MRR at cuts 10/14/20 and the latency non-inferiority gate remain unmeasured (`null`, not zero).

**A useful historical proxy was executable.** Previously overlooked, Git-ignored LTR exports contain thousands of ranked fused file candidates per query. Exact-file replay on these real exports shows truncation losses and rejects the specific predeclared 12/12/10 quota rule as a general replacement: it loses six net gold files on WHERE-78 while gaining one on holdout36. This is not evidence about current H-91a, not a synthetic quality gain, and not proof that all quota designs fail.

No production/champion modifications, installs, network calls, provider construction, model inference, or training were performed. Other agents' processes and files were not touched. This is executor B's handoff for the parent's join, not a cross-workstream consolidated report.

## Evidence search and sufficiency

Machine-readable inventory: `artifacts/research/2026-09-05/candidate-budget/audit.json`.

* Examined 515 JSON files under `.code-diver/reports`, `.code-diver/traces`, `artifacts/ltr`, `artifacts/ce_meta_ranker`, plus the two root result files. Thirty were empty/invalid JSON and are explicitly listed, not treated as negative quality results.
* Found 126 reports with 9,768 nonempty `query_plan` objects (run occurrences, not independent cases). **Zero** joined any target dataset on both `case_id` and exact question. Plans do exist, contrary to the earlier broad absence claim; they are not usable target evidence. Their persisted `retrieved_files` lists reach at most 14, not a full deeper pool.
* `h83_results.json` has 229 rows, each with ten retrieved files. Its settings say `30/10`, ranker `none`; this cannot establish recall34 or be promoted to an H-83/H-91a control. The historical LTR companion reports also say `30/10` despite identifying the H-66b config. Current config hashes do not repair historical manifest drift.
* Inventoried 282 trace JSONL files (4,811,854,781 bytes); fully parsed the 28 with `intellij` in their path (762,842,059 bytes, zero JSON parse errors). The other 254 were inventoried but not parsed. This is a declared filename-bounded audit, not a proof of absence everywhere, including external `/tmp` or caches.
* Historical IntelliJ hybrid traces contain at most 60 logged candidates, upstream of graph-file fusion; they are not the merged CE input. In `intellij-h74-agentic-where.jsonl`, 996 CE requests each contain 34 documents, and 996 responses each contain only 30 scores. There are 249 request and 249 response events with exact target query text, but no explicit case/query/request join IDs; each event type has 602 repeated-query occurrences. Request/response order is interleaved (the first request and response even have different query texts). Thus these are genuine persisted CE documents, **not** a safely joined H-91a 34/60/80 export. No adjacency join or inferred missing CE scores was used.
* Six LTR JSONL exports were audited, all using 13 pre-CE features rather than H-91a's 16 CE-meta features. `where79.features.jsonl`: 135,013 rows / 79 queries, 900–2,315 candidates per query. `holdout36.features.jsonl`: 62,319 rows / 36 queries, 1,230–2,263 candidates. The concatenated synthetic training export overlaps its source files and must not be counted as independent evidence.

The existing `replay_pool_recall.py` builds a vector store/embedding strategy and re-executes probes; `replay_rerank_depth.py` additionally constructs the actual reranker. Neither is a persisted-data-only replay. They were read but **not run**, respecting the offline restriction.

## Diagnostic protocol and provenance

`scripts/research_candidate_budget.py` is standard-library-only. Its loader validates feature schema, finite values, contiguous unique base ranks, unique file paths, and query consistency. It reconstructs selectors from only path, exported base rank, and signal features; serialized `label` fields are discarded. Labels from the current hashed dataset are joined only for metrics, using exact `case_id` plus exact query text. Missing/extra IDs are reported.

Source provenance is `GraphFileRetrievalStrategy._ordered_with_ltr`, which exports all ranked `FileScore` candidates before the final `ordered[:limit]` slice. `LtrFeatureExtractor` maps vector/lexical/graph signals explicitly, and `LtrFeatureCollector.write_jsonl` adds labels afterwards. Audited current source hashes are in the manifest; historical source/corpus identity cannot be independently verified. The signals are fused-stage channel scores, **not original per-channel retrieval lists or probe provenance**.

Rules fixed before inspecting replay metrics:

1. Baselines take the first 34, 60, or 80 files by exported base rank.
2. Quota34 takes up to 12 positive-vector-score files, then 12 positive-lexical-score files not already selected, then 10 positive-graph-score files not already selected. Each lane sorts by descending signal, then exported base rank and path. Missing lane capacity is backfilled in base order. Final presentation retains base order. Overlapping lanes cannot duplicate files.
3. No tuning, randomization, learning, or label-dependent selection. Unit tests verify order stability under reversed input, ties, overlap/backfill, short pools, missing provenance, invalid ranks, provider-error exclusion, and label invariance.
4. Strict exact-file, deduplicated labels only; glob cases are excluded. Both replayed datasets have zero glob cases and zero duplicate normalized queries, so `full`, `no_glob`, and `exact_only` label-policy slices coincide here. No fuzzy/suffix matching is used.
5. Full means the complete **persisted fused export**, not the corpus universe. Slicing a historical single-query export is a diagnostic only: it does not reproduce depth-dependent multi-probe retrieval/merge or CE preserve-top/second-pass behavior.

## Actual results

All 78 current WHERE cases join the 79-query export; the only extra ID is `where-json-file-parsing`. Holdout joins 36/36. No matched queries differ in text and no current case is missing. Per-case hits, missing gold, quota rescues/losses, tie flags and selected paths are in `where78.json` and `holdout36.json` under the artifact directory.

| Persisted-pool selection | WHERE-78 gold hits / 115 | Micro recall | Macro recall | Holdout36 gold hits / 36 |
|---|---:|---:|---:|---:|
| Fixed34 | 91 | 0.791304 | 0.834615 | 32 (0.888889) |
| Fixed60 | 96 | 0.834783 | 0.864957 | 33 (0.916667) |
| Fixed80 | 98 | 0.852174 | 0.880342 | 33 (0.916667) |
| Quota34 | 85 | 0.739130 | 0.797222 | 33 (0.916667) |
| Full exported pool | 113 | 0.982609 | 0.995726 | 36 (1.000000) |

Holdout micro and macro recall coincide (one expected file per case). No post-CE MRR/nDCG/recall or CE runtime is inferred from this table.

WHERE fixed34 misses 22 gold files present deeper in the export, versus two absent from the export entirely. Fixed60 recovers five of those 22, fixed80 seven. Holdout fixed34 misses four present deeper, with one recovered by fixed60/80. These are concrete candidate-budget bottlenecks in the historical proxy, not current answer-pipeline estimates.

Negative cases:

* WHERE quota34 rescues six gold files across six cases and loses twelve across twelve cases (two cases have both), net −6/115 or −5.2174 percentage points. Holdout rescues `where-holdout-inlay-hints` and `where-holdout-wolf-problems`, but loses `where-holdout-fus-event-log`: net +1/36.
* `where-command-processor` lacks both `CommandProcessorImpl.java` and `Undo.java` at their expected paths even in the full export. A selector cannot rescue them; missingness does not establish whether retrieval or stale labels caused the absence.
* Five WHERE cases and one holdout case tie on fused score across ranks 34/35. Exported rank is the deterministic tie-break; changing the upstream order remains an unmeasured sensitivity, not something the selector should silently randomize.
* The JSON audit counts 1,220 nonempty `error` objects across historical files, not 1,220 unique provider failures. Error rows are not scored as zero-quality pools. An explicit provider-error fixture tests this distinction; no runtime failure was induced. Missing pool cases would be reported rather than silently filled.

## Independence, hashes, and limitations

`audit.json` stores SHA-256 for every parsed JSON/feature/IntelliJ trace, target datasets, current H-66b/H-83/H-91a configs, both replay scripts, relevant exporter source, `uv.lock`, `pyproject.toml`, `package-lock.json`, CE-meta manifest/model, GGUF, and graph artifact. Each replay output includes input and script hashes. Python was 3.14.2; no third-party dependencies were imported.

Key immutable inputs:

| Input | SHA-256 |
|---|---|
| WHERE feature export | `39366febd8ab4aefbc00850381d3417bb8eebf981b01e11e012bd8d1befc25c1` |
| Holdout feature export | `ff31224a2c8103873f8b00a91922a1f66ac485b53e31506f849c539cc166e722` |
| WHERE-78 dataset | `0d0ac47ce100eebc7e006be209d06cf695f3e26a72f34e56e22ae376fd50a30a` |
| Holdout36 dataset | `239886362d344c521a9b77672315da5ca14e7818d2d267624e762a3ab6dc2afb` |
| Current H-91a config (both names identical) | `4052a6528a4643c615453aec8f8b7ba518a4b336ffdd059a23a6652cb3db24f9` |

The 229-case mech dataset has seven duplicate normalized-query occurrences and eight glob cases; the 1,065-case answer-set dataset has 28 and 35, respectively. WHERE's export overlaps both by 79 IDs/normalized queries; **these are not independent validation sets**. Holdout36 has zero ID/query overlap with the three main target datasets. The historical synthetic training export has zero ID/normalized-query overlap with all four targets, but semantic leakage and generation provenance remain unverified. This alone does not authorize training.

H-91a declares 856 train / 209 test queries, seed 42, but supplies no audited assignments or source feature dump. Its train/test overlap and contamination of these evaluation cases are therefore **unknown**, not zero. Feature labels were generated from evaluated cases in historical exports but are ignored by selection. No new labels/features were generated by a model. A leakage-clean semantic slice cannot be established from these artifacts.

The current graph hash is not a source-corpus/Qdrant snapshot hash; the historical corpus and exact export config/code snapshots are unknown. No service was queried to fill this gap. The holdout is small and previously evaluated; quota differences are descriptive, with no significance or non-inferiority claim. The runtime budget for deployed CE was not declared and cannot be substituted with offline script time.

## Exact validation commands

Run from `/Users/iurii.medvedev/Work/code-diver`. All writes below stay in the owned candidate-budget artifact directory. Initial two-case smoke passed before full replay; the final script was then tested and the same smoke/replays repeated after audit instrumentation changes.

```bash
python3 -B -m unittest discover -s tests -p test_research_candidate_budget.py -v
python3 -B scripts/research_candidate_budget.py --audit --out artifacts/research/2026-09-05/candidate-budget/audit.json
python3 -B scripts/research_candidate_budget.py --features artifacts/ltr/holdout36.features.jsonl --dataset datasets/intellij_eval_where_holdout.jsonl --cases 2 --out artifacts/research/2026-09-05/candidate-budget/smoke.json
python3 -B scripts/research_candidate_budget.py --features artifacts/ltr/where79.features.jsonl --dataset datasets/intellij_eval_where_only.jsonl --out artifacts/research/2026-09-05/candidate-budget/where78.json
python3 -B scripts/research_candidate_budget.py --features artifacts/ltr/holdout36.features.jsonl --dataset datasets/intellij_eval_where_holdout.jsonl --out artifacts/research/2026-09-05/candidate-budget/holdout36.json
```

Final results: **10/10 tests passed** (`tests.txt`); audit 12.667 s, smoke 0.323 s, WHERE replay 0.820 s, holdout replay 0.380 s. Each bounded execution was far below five minutes. Timings include parsing/hash work and are not CE latency. Full replay metrics were identical across both executions. Fixture tests are correctness checks, not quality evidence.

## Next experiment and parent join

Keep champion unchanged. Do not train a selector or tune these quotas on the reported outcomes. Parent should first obtain a frozen, provenance-complete export for a newly declared independent case set, with run/case/probe/request IDs; original query plan; separate raw channel ranks and scores; depth-specific merged pools for 34/60/80; exact CE input paths/documents; all first/second-pass CE scores/features; error and timing records; and dataset/config/model/corpus/dependency hashes. Depth-dependent pools must be captured separately, not synthesized by slicing one deepest multi-probe pool.

The data-producing runtime step needs separate explicit authorization; it is **not part of this offline task**. With that export, preregister recall/MRR non-inferiority margins and a latency budget, smoke two cases, then run the bounded offline comparison of fixed34, frozen quota34, fixed60/80 at cuts 10/14/20, paired by case ID. Report absent-pool versus rerank losses, rescues/regressions, provider failures and tie sensitivity before considering any learned selector. Require explicit disjoint query-ID and normalized/semantic-query split evidence before training.

Executor B is complete and ready for the parent's join. No cross-agent consolidated document has been created here.