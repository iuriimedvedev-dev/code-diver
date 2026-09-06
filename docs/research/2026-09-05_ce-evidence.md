# R1/R2: bounded live CE evidence, 2026-09-05

## Verdict and scope

**R1: inconclusive; equal-budget comparison blocked by the runtime limit. R2: inconclusive, with a positive exploratory WHERE signal. Neither hypothesis is confirmed and no arm is promoted.** This is executor A's handoff, not the parent R1–R4 joined conclusion. Join records by `case_id` and `experiment`; do not count smoke queries twice.

Read plan: `.plans/2026-09-05_search-hypothesis-tests.md`. Latest instruction overrides the old R2 proxy: test path/signature plus query-matched source excerpts, not H62's query-independent declaration summary. Only research script, its tests, this document, and the owned artifact directory were intentionally written. No dependencies installed, paid APIs called, services started/stopped, or production/champion files edited. CE requests were sequential; exclusive CE ownership was supplied by the parent. Other agents' offline work could still affect wall time.

## Hypotheses and actual design

R1 rationale: an 850-character indexed-content prefix may hide useful evidence. Select first-pass scores strictly below 0.3, in base-rank order, cap 24, rebuild at 2400 content characters, then merge `max(first, second)`. High first-pass scores remain unchanged, but their ranks are NOT protected against competing candidates improving.

Important manifest drift: current `intellij-h66b-champion.yml` already enables the second pass. The harness disables it **in memory**, then obtains one fixed 34-candidate base pool and explicitly executes the first pass. A same-retry-count/base-rank control spends the same maximum per-document budget on the first N candidates instead of the sub-floor selection. This is a budget-ceiling control, NOT exact token matching. The cheaper single-pass result is diagnostic, not an equal-cost control. H83 historical JSON was not used. Results are raw CE top10: the production preserve-top intervention is intentionally not applied, so this is not a champion end-to-end reproduction.

R2 uses H55's `intellij_h52_summary_head_first_qwen` collection and the same frozen 34 candidates for both arms. Both documents have the same path/signature prefix and **850 total characters maximum, including prefix**. The signature is the first declaration-like source line (at most 160 chars); it is a heuristic, not an AST signature. Head takes the source beginning. Fragment scans source line starts, maximizing distinct query-token overlap in the available window; CamelCase is split, a fixed stop-list removed, and ties choose the earliest offset. Both arms are extractive; expected labels are never used for selection. This deliberately controlled head is not byte-identical to H55's meaningful-head builder, and fragments are not H62's old proxy. It can retain copyright/import material; evaluate a meaningful-head baseline next.

R1's production fused-document builder limits **content**, not total document length. Its first batch actually contained 37,172 chars, not 34 × 850. R2 limits the entire document. Therefore do not compare R1 vs R2 as equal-cost arms across different collections.

## Commands and selection

All commands ran from `/Users/iurii.medvedev/Work/code-diver`, using existing dependencies and local endpoints. Artifact paths below are relative to that root. No full dataset evaluation was run.

1. `uv run --no-sync pytest -q tests/test_research_ce_evidence.py` — initially 4 passed; final expanded suite 5 passed.
2. `uv run --no-sync python scripts/research_ce_evidence.py --cases 2 --seconds 90 --out artifacts/research/2026-09-05/ce-evidence/smoke-01` — externally terminated after 110 seconds, no persisted report or stdout; its internal progress/call count is unknown. Do not infer zero CE calls.
3. `uv run --no-sync python -X importtime -c 'import sys; sys.path.insert(0,"scripts"); import faulthandler; faulthandler.dump_traceback_later(10,exit=True); import replay_pool_recall'` — import-only diagnostic succeeded; stderr retained as `import-diagnostic.txt`.
4. `uv run --no-sync python scripts/research_ce_evidence.py --cases 2 --seconds 35 --out artifacts/research/2026-09-05/ce-evidence/smoke-02` — 35.003 s, interrupted budget-control call after successful first/selective calls.
5. `uv run --no-sync python scripts/research_ce_evidence.py --experiment R2 --cases 2 --seconds 65 --out artifacts/research/2026-09-05/ce-evidence/smoke-r2` — successful two-query smoke, 41.940 s.
6. `uv run --no-sync python scripts/research_ce_evidence.py --experiment R2 --cases 8 --seconds 90 --out artifacts/research/2026-09-05/ce-evidence/r2-eight` — 90.003 s, 7 complete pairs; final fragment call interrupted.
7. `uv run --no-sync python artifacts/research/2026-09-05/ce-evidence/summarize.py` — offline exact-label accounting; emits `summary.json`.

Counting the failed initial attempt, live-run wall time was approximately **277 seconds** (plus small launcher overhead), below five minutes; no additional CE requests followed. Alarm plus hard faulthandler watchdog were added after the first externally killed attempt. Eight distinct queries were selected before the bounded run: the first four non-empty records of WHERE and first four of mech150, in file order, no quality-based selection or random sampling. Smoke used only the first case of each dataset. This deterministic convenience sample is strongly biased toward configuration files in the guard slice.

## Actual results

### R1 smoke: one WHERE case, not a full experiment

`where-project-open`: 34 candidates, retrieval 25.993 s. First pass CE 5.370 s; selective retry CE 2.415 s; **22 retries**, 53,856 retry chars. Both arms: hit@10=1, hit@1=0, MRR@10=0.200, recall@10=0.250, nDCG@10=0.15102. No rescue or regression in this one pair. A high-score gold candidate, ProjectManagerImpl, scored 0.607319 and was not retried. The same-22-retry base-rank control submitted 53,470 chars but was interrupted after 0.642 s: **no valid equal-budget quality result**. Token counts are unavailable, not estimated. Only the retry-count bucket 22 has a real observation; no meaningful bucket p95 or guard-quality estimate exists.

### R2: paired intersection only

Exclude the eighth case (`config-platform-acp-resources-intellij.platform.acp.xml`) entirely from paired quality and latency aggregates because its fragment score batch did not complete. The head-only result is preserved in raw data, not silently counted as a fragment failure.

| Slice | Complete pairs | Head hit@10 | Fragment hit@10 | Head MRR@10 | Fragment MRR@10 | Head micro recall@10 | Fragment micro recall@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| WHERE | 4 | 0.5000 | 0.7500 | 0.15625 | 0.19792 | 0.3000 | 0.4000 |
| mech exact guard | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| all exact-only | 7 | 0.2857 | 0.4286 | 0.08929 | 0.11310 | 0.17647 | 0.23529 |
| no-glob cases | 6 | 0.3333 | 0.5000 | 0.10417 | 0.13194 | 0.23077 | 0.30769 |

Hit@1 is zero in both arms on every complete pair. WHERE macro recall rises 0.1875 → 0.4375 and mean nDCG rises 0.13012 → 0.24234. All-pair mean nDCG rises 0.07435 → 0.13848. One hit rescue: `where-find-usages`, absent from head top10 → rank 3 (MRR 0 → 0.3333). One ranking regression: `where-inspections`, rank 2 → rank 3 (MRR 0.5 → 0.3333), same exact recall. Other paired hit/MRR values unchanged.

All three guard cases lack any exact gold file in their candidate pools; `where-refactoring` also lacks gold. Thus guard zero/zero is **not evidence of non-regression** or fragment quality. Exact labels were not expanded by basename or glob. One selected record includes a permissive `glob:**/resources/META-INF/plugin.xml`; it is removed for exact-only metrics and the entire case excluded for the no-glob slice. Full/glob scoring is not the acceptance metric and was not validated. Historical raw aggregates initially counted that glob as an unmatched literal in the recall denominator: use corrected offline `summary.json`, not raw aggregate recall. Raw rankings/documents/scores remain unchanged.

### Budget, latency, and provenance

Seven paired cases × 34 candidates = **238 documents per arm**. Identical maximum allowance; actual chars head 197,231 vs fragment 197,059 (172 fewer, 0.087%). Unequal actual lengths arise near EOF; this is equal character ceiling, **not exact token parity**. No tokenizer usage was exposed by the provider abstraction. Query tokens, serialization and model tokenization were not measured.

Head CE sum/median/p95 (nearest rank, n=7): 20.117 / 3.146 / 3.449 s. Fragment: 15.358 / 2.043 / 3.091 s. Calls always ran head before fragment, with repeated smoke queries; cache/order/warmup effects and concurrent offline workloads confound speed comparisons. Fragment construction time is included in overall runtime, not CE timing. Do not claim causal speedup. R2 retries: zero by design.

75/238 fragment offsets were nonzero. Source path and SHA256 were recorded for every candidate; 228 unique source files in the complete pairs. Raw calls persist exact rendered documents and scores, enabling independent reconstruction. Observed-source manifest SHA256: `e22aa64f89c92832dd6dbdaaced275b1699b28dfc91391693694e38039869842`. This is NOT a hash of the full indexed collection.

## Offline checks and independence gate

Final command `uv run --no-sync pytest -q tests/test_research_ce_evidence.py` passed **5 tests** (`tests.txt`). Tests cover query-specific evidence beyond the head, source-contiguous extraction and 850-char cap, unmatched query fallback, short source, invalid budget, retry floor/cap, high-score preservation, exact metrics/ties/absent gold, and actual production `_with_second_pass` fallback with a deliberately failing offline provider. The mock is failure injection only; it supplies no quality scores. Zero retries makes no provider call. These validate representation/control logic, not model quality.

Local CE `/health` returned ok; embedding `/v1/models` returned HTTP 200; Qdrant collections and aliases were available. Observed aliases: H66b → `intellij_h66b_budget_qwen__staging_4fa4c6c030d2440daeeefc996ded6473`; H52 → `intellij_h52_summary_head_first_qwen__staging_be6df5119da54a2d97dd4fbad0f5af2d`. Full collection payload/version hash and served-model identity are not independently attested. GGUF file SHA256 is `c04f5f5657c52e04538c455e8c62817db3d3b795b39e9f547f8581510445f075`; this proves local file identity, not which weights the endpoint loaded. Configured CE: local llama.cpp Qwen3-Reranker-0.6B on :8081, timeout 15 s; embedder Qwen3-Embedding-0.6B-4bit-DWQ on :8001; no generation calls.

Dataset SHA256 and counts:

| Dataset | Rows | Duplicate normalized queries | SHA256 |
|---|---:|---:|---|
| WHERE | 78 | 0 | `0d0ac47ce100eebc7e006be209d06cf695f3e26a72f34e56e22ae376fd50a30a` |
| mech150 | 229 | 7 | `e9e5ae2b55fa875d6c40718b985dc44eadbd7b10899c3024888158328ba58629` |
| answer_sets | 1065 | 28 | `30511f63ad15a4466f9dd9066cd7d4b88816385ca63a264c1bf2ef3ad6598962` |

Selected eight queries have zero normalized duplicates. H66b config SHA256 `fe3c0cee5135a27c62d6e8ebfbbcfbdb217b3cc006fbbf250640d8e288525ce4`; H55 config `fb57bbf7152daaf714d95990cb997c0871dda425cfb12dba6a2b130226c2a4fc`; dependency lock `uv.lock` SHA256 `0e8d95fbef57ffdfb6eecb72395dd393959765d72b255d6704bbfc85d85f3dab`. This hashes the lock, not installed-package bytes. Per-run harness/config/model/dataset hashes are in raw reports; later instrumentation and exact-label accounting edits mean the final harness hash differs. Raw file hashes are in `summary.json`.

No labels were generated, and no trained meta-ranker or fitted feature model was used. Extraction uses query/source alone. Historical CE training overlap, label-generation provenance, corpus leakage and a clean leakage slice remain **unknown/blocked**, not certified independent. The tiny convenience sample cannot support significance or suite-wide claims.

## Next test and handoff

First complete a frozen-pool R1 equal-token or explicitly equal-character-cost comparison on 4 WHERE + 4 diverse guard cases, with persistent raw pools so retrieval initialization does not consume the CE budget. For R2, counterbalance head/fragment call order, compare against meaningful head, enforce exact token parity with the served tokenizer, and select guard cases with gold present in pool. Include zero-retry and high-gold cases, unchanged-document controls, and one provider-failure injection. Do not expand beyond the user-approved budget without a new authorization.

Parent should join this executor's `smoke-02/results.json` (R1 partial) and `r2-eight/results.json` (R2 raw) with the corrected `summary.json`, after R3/R4 complete. No R3/R4 outputs were awaited or claimed here; cross-agent joining remains the parent's responsibility. The incomplete eighth pair and unobserved first attempt must stay explicitly flagged.