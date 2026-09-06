# Large paired search evaluation readiness — 2026-09-05

## Status and authorization boundary

**R2 N192 EXECUTED — 192/192 complete in2428.84s; negative result. JOIN before parent QA/final acceptance.** Architect's latest instruction supersedes the historical readiness restrictions below: R1 deferred, deadline4200 seconds, no denominator reduction, no tuning or promotion.

### Actual execution amendment (supersedes conflicting historical proposals below)

- Both foreground96-pair commands ran successfully (terminal timeouts3600s and2800s); shared absolute4200s deadline retained. ETA after12 pairs3499s. Errors0, all pools34, source fallback0, AB/BA96/96.
- Results: full hit0.8750→0.8646, MRR0.7922→0.7210 (delta95CI[−0.10658,−0.03713]), recall0.8503→0.8338; hit wins0/losses2. Guards have33/40 hits in both arms (40 paired ties), MRR/recall decrease; no paired gain justifying promotion. Rerank p50/p95 A2.697/5.511s, B2.877/6.208s.
- Retention bundle created: `artifacts/research/2026-09-05/large-search-eval/evidence.tar.gz` (~29MiB), SHA256 `5914a00564fe444f2592740e50aa2768287e9b83008e1487cbdfdcd0d2f8320a`. Verified202 files byte-for-byte. Parent must secure durable copy; no copy outside exclusive scope. Interface-generated `.output.txt` outside scope was detected and left untouched.
- `summarize` and offline `artifacts/research/2026-09-05/large-search-eval/analyze_retained.py` executed successfully; executor integrity checks passed (source/pool/frozen hashes, baseline/retry documents, alias mappings). Independent QA pending parent join, not claimed complete.
- Checkpoint SHA256 `a924f9dcf606629e2abb979230af232f76e100e4a29d6221454b753e8667cdad`; summary `c97ee8ad4c1fd71c519ddb1893c9b618faf5c7507e6b25802f3c82b434fab4db`. Report: `docs/research/2026-09-05_large-search-eval.md`; session: `.session/2026-09-05_large-search-eval.md`. Preserve ~172MiB raw evidence before cleanup; full hashes/limitations in report.
- New runner `scripts/research_large_search_eval.py`; new tests `tests/test_research_large_search_eval.py`; production and older scripts/tests untouched.
- Four initial test setup errors were caused by the missing parent directory for the explicitly scoped pytest temporary directory; directory creation resolved them. Expanded suite: 14 passed in 2.06 seconds.
- Live production parity smoke PASS: one real pool, two live CE calls (first + second pass), recorded-score replay through isolated unmodified arm. Documents, complete output objects and model input features match exactly. No live R2 quality used in smoke.
- Manifest frozen after parity: `artifacts/research/2026-09-05/large-search-eval/manifest.json`, SHA256 `a579c628a5f1e96157dc6df8adc2c4713627d5582c550009a8496ed5d9738a13`.
- Arithmetic confirmed: 78 WHERE + 95 reconstructed novel - 15 overlap + 34 added guards = 192; 40 non-WHERE mechanical guards, 118 selected mechanical. Dataset labels are preserved separately. Novel95 is NOT independent.
- Guard selection: seed42 proportional extension/top-level-family strata, largest-remainder allocation, deterministic shuffle. AB/BA 96/96, balanced within joint WHERE/novel strata to within one.
- Each arm uses new serialized-pool objects, config, provider, feature extractor, copied fan-in mapping and independent LightGBM Booster. Only first-pass B content changes; production retry, adjustments, meta-ranking and preservation are inherited unchanged.
- Foreground segments of at most96 pairs avoid exceeding the terminal's 3600-second per-call maximum; both segments share the original absolute 4200-second deadline, including inter-segment time. Resume only at a deliberate segment boundary, with provenance/source/pool validation; no interrupted arm splicing.
- At12 pairs and each12 thereafter, stop if projected completion exceeds4170 seconds; retain N192. Reserve300 seconds before starting a new pair and30 seconds before final deadline for checkpoint/cleanup. CE HTTP timeout stays60000ms. No background or daemon process.
- Actual preflight commands (project root): `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=artifacts/research/2026-09-05/large-search-eval/test-tmp tests/test_research_large_search_eval.py`; same environment with `scripts/research_large_search_eval.py smoke`, then `prepare`.
- Launch command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/research_large_search_eval.py run --max-pairs 96`; terminal timeout3600 seconds. Repeat only if first segment permits continuation and time remains. Summarize with the same prefix and `scripts/research_large_search_eval.py summarize`.
- Artifact retention: raw pools, rendered documents, scores, features, source hashes, per-call journal, atomic pair files and checkpoint remain in the assigned research artifact directory; report/session will link hashes. Directory is gitignored: parent must retain it before any worktree cleanup. No unapproved external destination written.

Scope is single-query search using H-91a, not answer-generation/multi-probe evaluation. A multi-probe claim requires an audited current case-joined probe/pool export and a different time estimate; historical replay/quota artifacts are not substitutes.

## Evidence reviewed and present readiness

Read `docs/research/2026-09-05_search-hypothesis-tests.md`, `2026-09-05_ce-evidence.md`, `2026-09-05_latency-independence.md`; `scripts/research_ce_evidence.py`, relevant replay/audit helpers, document builder and CE strategy; H91a/H66b/H55 configuration, current datasets and historical result/audit JSON.

- R2: only 7/8 complete historical pairs; WHERE n=4 hit10 0.50 to 0.75. Three guards had no exact gold in the pool: their ties do not establish non-regression. Fixed head-before-fragment ordering confounds latency.
- R1: one smoke pair, matched control interrupted; quality remains inconclusive.
- Historical quota34 was rejected; do not add candidate selectors or switch collections.
- LightGBM warm prediction was microseconds (default p50 0.084 ms, p95 0.149 ms), synthetic model-only evidence. No thread change or end-to-end attribution is justified.

Read-only endpoint checks during this readiness pass returned HTTP 200:

| Endpoint | Observation |
|---|---|
| `http://127.0.0.1:8081/health` | `status=ok` |
| `http://127.0.0.1:8081/v1/models` | `Qwen3-Reranker-0.6B-Q4_K_M.gguf`, reported context 40960 |
| `http://127.0.0.1:8001/v1/models` | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`, max length 512 |
| `http://localhost:6333/collections`, `/aliases` | collections and aliases available |
| `http://localhost:6333/collections/intellij_h66b_budget_qwen` | green, optimizer ok, 136578 points, 136192 indexed vectors, 1024-dimensional cosine |

H66b alias resolves to `intellij_h66b_budget_qwen__staging_4fa4c6c030d2440daeeefc996ded6473`; H52 resolves to `intellij_h52_summary_head_first_qwen__staging_be6df5119da54a2d97dd4fbad0f5af2d`. These are metadata observations, not immutable corpus hashes or proof of loaded weight bytes. HTTP health does not prove inference capacity or exclusive ownership. Recheck immediately before an approved run; obtain exclusive CE access from parent, not by terminating other processes.

`uv`, `curl`, `.venv/bin/python` exist. The project interpreter is Python 3.12.12; module discovery found pytest, LightGBM, httpx, YAML, qdrant_client and code_diver. System `python3` is 3.14, so use the project interpreter. No dependency installation/import benchmark was needed. Repository root `../intellij-community`, graph artifact (731673660 bytes), GGUF (396476288 bytes), and meta-ranker files exist. Availability of every selected source and successful real model loading remain run preflight gates.

Repeatable read-only checks from project root:

```sh
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8081/health
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8081/v1/models
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8001/v1/models
curl --fail --silent --show-error --max-time 5 http://localhost:6333/aliases
curl --fail --silent --show-error --max-time 5 http://localhost:6333/collections/intellij_h66b_budget_qwen
```

## Champion fidelity and R2 intervention

Freeze `configs/intellij/intellij-h91a-champion.yml` as A. H91a uses H66b storage, 34 CE candidates, 850 **content** characters, enabled second pass (floor 0.3, cap 24, 2400 content characters), preservation margin 0.1, meta-ranker with hub fallback, and CE timeout 60000 ms. Keep retrieval, graph/hybrid settings, tie handling, learned model/features, final preservation, retry policy and timeouts identical in A and B. Never silently substitute hub fallback for a loaded champion model.

Retrieve once per unique case/query, capture ordered full candidate objects and all metadata/base scores needed downstream, and replay the identical immutable pool to both arms. Do not persist only file paths: document construction and model features need more. Do not retrieve separately per arm or add gold files to pools. Preserve fewer-than-34, absent-gold and source-missing cases explicitly.

- **A:** unmodified champion document builder and reranking pipeline, including production second pass and final top10.
- **B:** replace only the first-pass content payload with deterministic query-aware source fragments. Keep champion path/title/base-score envelope byte-identical and the 850-content-character ceiling. Freeze the tokenization/stop-list/earliest-offset tie policy before scoring; no gold labels enter extraction. Do not reuse the old custom total-850 path/signature wrapper as the champion baseline.
- Keep the second-pass expanded document builder unchanged in both arms for this first experiment. The same score-dependent retry policy can select different candidates/counts because B changes first-pass scores; this is a downstream consequence, not a policy change. Record it. Extending fragments into retry documents would be a separate intervention requiring approval.
- Missing/unsafe/unreadable source in B uses A's exact document with a recorded reason, never drops a candidate. Record source offsets, rendered strings and source hashes. Original candidate metadata stays unchanged for downstream features; record the actual CE-derived features for each arm.

This is a champion-versus-fragment intervention, **not** a pure meaningful-source-head-versus-fragment experiment: champion A uses fused indexed content. The historical H55 head comparison can remain diagnostic evidence but cannot be pooled into this result.

Budget equality means identical candidate pool and configured character/call ceilings, **not exact realized character or token equality**. At most 34 first-pass plus 24 retry documents per arm. Actual lengths and retry counts must be reported. If parent requires exact token/count parity rather than equal ceilings, HOLD: an unchanged score-dependent champion cannot guarantee that parity. A separately approved matched-cost ablation must not be mislabeled champion.

## Dataset accounting and recommended fixed N

Read-only recount and hashes match the prior audit:

| Dataset | Rows | SHA256 |
|---|---:|---|
| `datasets/intellij_eval_1000.answer_sets.jsonl` | 1065 | `30511f63ad15a4466f9dd9066cd7d4b88816385ca63a264c1bf2ef3ad6598962` |
| `datasets/intellij_eval_where_only.jsonl` | 78 | `0d0ac47ce100eebc7e006be209d06cf695f3e26a72f34e56e22ae376fd50a30a` |
| `datasets/intellij_eval_mech150.jsonl` | 229 | `e9e5ae2b55fa875d6c40718b985dc44eadbd7b10899c3024888158328ba58629` |

WHERE78 is contained by ID/query in mech229, both inside1065; do not budget or count them as 307 independent queries. Preserve dataset-specific expected labels when rescoring shared predictions; one WHERE answer set differs. Full1065 has 1037 normalized queries and reconstructed split856/209. The audited **95 reconstructed query-and-answer-novel** IDs are a reporting slice, **NOT certified independent**, because original training features/IDs/corpus provenance are missing. Do not reconstruct95 from WHERE/mech's separate splits.

**Recommended conditional large run: R2 N=192 unique case IDs**, selected before inference:

1. All78 WHERE IDs.
2. All95 novel IDs from `artifacts/research/2026-09-05/latency-independence/audit.json`, under `audit.datasets.intellij_eval_1000.answer_sets.slices.query_and_answer_novel` (accept an unwrapped audit object only after schema validation). Fifteen overlap WHERE, yielding158 unique IDs.
3. Add34 mechanical non-WHERE, non-novel IDs from145 eligible rows, deterministic seeded stratification by expected-file extension and top-level path family. Freeze the exact quota table, selection algorithm and full ordered IDs in a manifest before CE. Use seed42; never select by observed arm performance.

Result: all78 WHERE, all95 novel, and40 non-WHERE mechanical guards (6 novel guards plus34 added); total192. Mechanical coverage is118/229 including WHERE, not full mech229. Report slice intersections, not a sum of independent sample sizes. Do not select only pool-gold-present guards: keep the prespecified full guard sample and additionally report the pool-present diagnostic subset. If guard pool coverage is inadequate under parent's threshold, declare non-regression unassessable rather than replacing cases after scoring.

The full1065 remains the desired **exploratory regression** run, not an independent test or a promise inside45 minutes. Its remaining873 IDs require separate authorization/checkpoint continuation. Full mech229 plus all95 novel would be303 unique cases (21 overlap), not324; also unlikely to fit45 minutes with champion retries.

## Runtime estimate, finite budget, and fallback decision

No fresh CE timing was taken. Historical R2 complete-pair mean CE was5.068 s; warm retrieval mean over the six post-initial complete cases was3.600 s. Their sum8.668 s is only a lower-fidelity planning proxy, excluding some construction overhead and champion retries/postprocessing. First historical retrieval took22.233 s (R1:25.993 s). One R1 first CE took5.370 s and22-document retry2.415 s. Extrapolating those observations to champion gives a **12–20 s/pair sensitivity range**, not a measured confidence interval; slow retrieval/provider cases may exceed it.

Times below include30 s initialization, exclude optional R1 and final reporting, and assume sequential calls and one shared retrieval per pair:

| Unique N | Old R2 proxy | Champion at12 s/pair | Champion at20 s/pair |
|---|---:|---:|---:|
| WHERE78 | 11.8 min | 16.1 min | 26.5 min |
| Novel95 alone | 14.2 min | 19.5 min | 32.2 min |
| Proposed192 | 28.2 min | 38.9 min | 64.5 min |
| Full mech229 | 33.6 min | 46.3 min | 76.8 min |
| mech229 union novel95 =303 | 44.3 min | 61.1 min | 101.5 min |
| Full1065 | 154.4 min | 213.5 min | 355.5 min |

Therefore **192 completion within45 minutes is conditional, not ready to promise**. Full1065 would need under2.25 s/pair within a2400 s data budget, already below historical paired CE alone. Do not propose concurrency or omit champion stages to force that estimate.

After explicit launch authorization, use one2700 s campaign deadline starting before imports/model/graph loading, including preflight, calibration, writes and optional R1. Reserve the final60 s for reporting; R2 stops by2400 s; optional R1 gets at most240 s. The first12 scheduled R2 pairs are a throughput checkpoint, included exactly once in N192, not a separate quality-tuned pilot. Counterbalance their order and include WHERE/novel/guard strata. Continue only if the observed initialization plus projected192-pair time and20% headroom fit2400 s. Recompute ETA after each12 pairs; never start a pair whose bounded calls cannot fit the remaining time. No results-driven sample-size adjustment.

At12 s/pair without extra overhead,192 needs2304 s: close to the ceiling and may fail the headroom gate. If throughput fails, stop at a valid checkpoint and return HOLD; request a separately frozen smaller run (e.g. N120 with all78 WHERE plus42 guards, acknowledging incomplete novel95) or more time. Do not silently relabel a partial192 as a complete powered test. No power claim is possible from the tiny prior sample without parent selecting a minimum effect and design assumptions.

## Optional R1, only if matched control is feasible

R1 is secondary; do not consume R2's reserved completion budget. Prespecify **N=8** from the192 manifest, four WHERE and four non-WHERE guards, before inference. Use the same champion pool and one shared champion first-pass score vector; compare selective sub-floor retries versus first-k base-rank retries, where k is the selective count, cap24. Both use production expanded documents at2400 content characters and `max(first, second)`, then identical champion adjustments/meta-ranker/preservation. The no-retry first pass is diagnostic only, not the matched-cost control.

This matches retry count and content ceiling; it does not match actual tokens. Require parent's explicit acceptance of that cost definition. Report actual chars and tokenizer counts if verifiably available, otherwise tokens=null with the reason. If exact-token parity is required and the served tokenizer/budget matcher is unavailable, omit R1 and report BLOCKED. Do not pad/truncate only one arm covertly or invent token counts.

For valid R1 latency, execute selective/control in4 AB and4 BA orders around their shared first pass; do not compare a reused earlier R2 latency with a new control timing. Budget maximum656 scored documents (8 × [34+24+24]); R2 maximum22272 (192 × 2 × [34+24]). Retry-zero cases issue no retry HTTP call. Report retry buckets0,1–8,9–16,17–24, high-first-score-gold cases, unchanged control/selection overlap and all failures. Buckets absent in live data remain unobserved; cover zero retry and provider failure using offline tests, not forced live failures.

## Metrics, counterbalancing, errors, and provenance

- Primary reporting: paired final champion-output hit@10, MRR@10 and macro recall@10, plus micro exact recall, paired deltas, rescues/regressions and denominators. Raw CE top10 is a separate stage diagnostic. Exact-file gold excludes globs, wildcards and directory labels; include a no-glob-case sensitivity slice. Keep existing full matcher scoring secondary and explicitly labeled.
- Report full selected192, WHERE78, non-WHERE guards40, audited novel95, and deduplicated-query sensitivity; none certified independent. For future1065, report exploratory regression plus the same fixed95 slice. Do not aggregate reused predictions as additional observations.
- Preassign96 AB /96 BA R2 orders using a seeded, stratified schedule; sequential CE worker=1. Alternate order within strata as nearly evenly as possible. Record actual timestamps/order and exclusive-service declaration. No repeated warming queries outside the budget. Separate process/model startup, first-query and warm observations; do not call them service-cold because services are not restarted.
- Stage timings: retrieval/embedding where observable, source read/extraction, first CE, retry CE/counts, feature extraction, model load, model prediction, preservation/finalization, serialization; per-arm warm p50/p95 and paired latency deltas, with explicit percentile estimator (linear) and n. Include shared retrieval in each reconstructed arm E2E once, but in campaign wall time only once. Distinguish reconstructed paired E2E from separately measured standalone searches; cache/order remain possible confounders.
- Planned/attempted/complete/failed/not-started counts per slice; source coverage and pool exact recall/hit coverage; CE missing/duplicate/out-of-range/nonfinite scores, timeout/error type, first-pass/base fallback, retry fallback, meta-ranker/hub fallback. Failures must not masquerade as successful champion results. Preserve operational fallback rankings separately from complete-pair quality. Report conservative missing-pair bounds alongside successful-pair metrics; never convert incomplete pairs to zero silently.
- For uncertainty, paired bootstrap deltas with seed42 and10000 replicates; include dependence-aware sensitivity clustering normalized queries/shared-answer families. Hit discordance/exact McNemar is descriptive; no independent-case significance claim or cross-slice p-value fishing. Parent must set primary slice, effect floor, guard non-inferiority margin, latency budget and coverage/error tolerances before execution.
- Append/flush a durable event after each retrieval and provider call, not only after a whole pair; atomic checkpoint after each pair. Store failed/interrupted arms, exact documents, scores, features and timing. Resume only against identical config/model/data/pool/source/runner hashes and order manifest; prohibit overwriting. Never splice timings from different sessions into one complete-pair latency observation; rerun such timing pairs explicitly and retain attempt history.
- Freeze SHA256 for datasets, selection/slice IDs, runner/tests, resolved config, lock, meta model+manifest, GGUF, graph, source contents, candidate serialization and final outputs. Record git revision/dirty state, installed package versions, endpoint model metadata and physical collection alias before/after. Source manifests and collection metadata do not certify full indexed-corpus identity; retain that limitation if no immutable index snapshot exists. Persist final artifact archive outside ephemeral worktrees on the parent-approved durable destination; research artifacts are gitignored.

Current measured hash anchors: H91a config `4052a6528a4643c615453aec8f8b7ba518a4b336ffdd059a23a6652cb3db24f9`; existing CE runner `cb0b097a1d6b1f7a26491151369aa937b854b1d797dd3128a7a661585f642927`; lock `0e8d95fbef57ffdfb6eecb72395dd393959765d72b255d6704bbfc85d85f3dab`; meta manifest `e74f538ff7ca54036e834ea9ab227244537155ed825d715c97ba9596abfca688`; model text `8dcadfdc02b050fd35ebafca7f436c822859ff38cfeba4f9bd1203abc90e5010`. Large graph/GGUF were checked for existence/size, not rehashed in this readiness pass.

## Required runner changes — future authorization only

Allowlist proposed for the implementation agent: `scripts/research_ce_evidence.py`, `tests/test_research_ce_evidence.py`, research manifests/results under an assigned artifact directory, and this plan. No edits to `src/`, production configs, champion/model artifacts, collections or datasets. If faithful injection cannot be implemented inside the research runner, escalate rather than broadening this scope.

1. Replace fixed cases choices1/2/8/10/12, first-N selection and hardcoded H66b/H55 configs with validated manifest/config inputs and explicit single-query mode. Current script cannot run192/1065 and `--seconds` is silently capped at300 by both alarm/watchdog logic.
2. Build a research-only immutable-pool adapter and faithful champion execution path. Reuse production stage behavior; test A equivalence with real production strategy on deterministic offline fixtures. B document injection must affect only the first pass: production second pass calls the builder directly, not `_document`, so an indiscriminate monkeypatch risks changing both stages.
3. Add deterministic selection/order, per-call event journal, atomic checkpoints, strict resume/provenance validation, complete-pair joins, explicit fallback/error capture and per-stage timers. Replace five-minute hard exits with a campaign-wide monotonic deadline and bounded calls, preserving checkpoint grace.
4. Add optional matched R1 with its own counterbalanced retry order and remaining-budget gate. Reject incompatible exact-cost requirements rather than relaxing them silently.
5. Offline tests: baseline fidelity incl. meta/preservation and retry; fixed pool/metadata immutability; content-vs-total budget; deterministic fragments; safe-path/source fallback; unchanged documents; score validation/ties; empty pools; deadline mid-arm; atomic resume/hash mismatch; AB/BA balance; nested-slice/dataset-specific labels; retry-zero/high-score gold/control count; real production fallback under injected failure. Fake scores are test fixtures only, never benchmark evidence.

Proposed CLI contract below is **not implemented and must not be executed now**. Paths are project-root-relative; implementation must reject missing manifests and refuse overwrite. `--prepare-only` must be offline and perform no inference; its manifest must be reviewed by parent before running.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/research_ce_evidence.py --prepare-only --config configs/intellij/intellij-h91a-champion.yml --selection where78-novel95-guard34 --seed 42 --manifest artifacts/research/2026-09-05/large-search-eval/selection-192.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -p no:cacheprovider tests/test_research_ce_evidence.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/research_ce_evidence.py --config configs/intellij/intellij-h91a-champion.yml --manifest artifacts/research/2026-09-05/large-search-eval/selection-192.json --experiment R2 --optional-r1-cases 8 --seconds 2700 --r2-seconds 2400 --workers 1 --seed 42 --out artifacts/research/2026-09-05/large-search-eval/run-01
```

## Parent join checklist

Approve champion identity and single-query scope; equal-ceiling versus exact-token meaning; first-pass-only R2 intervention; deterministic N192/guard manifest; primary metric/slice and numeric acceptance thresholds; error/pool coverage gates; optional R1 cost definition; exclusive service slot; implementation allowlist and durable output location. Review runner tests and fidelity evidence before assigning launch. If any gate remains open, status is HOLD. No arm promotion, production change, or full1065 claim follows from readiness.