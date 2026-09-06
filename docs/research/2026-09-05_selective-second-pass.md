# R1 selective second-pass research — 2026-09-05

## Restoration and current status

The post-QA integrity review found this report replaced by the QA appendix alone. The detailed research account below is reconstructed from retained artifact metadata, the intact session/plan and recorded execution history; it is not a claimed byte-for-byte recovery. The original QA appendix is preserved verbatim at the end. Its “100% parity in ranking quality” means equal measured hit/MRR/recall, **not identical rankings, features or predictions**.

LIVE192 completed and the prespecified descriptive gates passed. QA subsequently reported 69 passing tests and clean diff. No automatic promotion: the parent owns the final decision. Production, champion and services were not changed by this research or this documentation repair.

## Frozen protocol and evidence classification

- A: production retry eligibility strictly below 0.3, cap24; indexed content expands from850 to2400 characters. Production first stage, score adjustments, max merge, meta-ranking and preservation remain active.
- N: no-retry ablation, conditional on saved first scores.
- S: filter baseline eligibility without refill. Indexed content must actually exceed850 characters, and a query term must occur wholly inside characters850:2400 but be absent from the first850. Frozen CamelCase/lowercase/alphanumeric tokenization and STOP list; whole-content spans prevent artificial boundary tokens. No labels enter policy selection.
- C: deterministic matched random within baseline eligibility, seed42, SHA256 case/candidate ordering, matching S counts in256-character expanded-document strata, then restoring production order. Report realized overlap and character gaps; no redraw or tuning.
- Counts and characters are not tokens, equal compute or measured speed. Frozen-score subsets are conditional offline screening, **not exact live replay**, because CE scores depend on batch composition.
- Saved evidence contains192 pools,6528 first scores,1061 retry scores and71 zero-retry cases, indexed content/metadata/fan-in and downstream outputs/features/predictions. Missing expanded scores outside baseline eligibility cannot be invented; older CE evidence does not supply production-equivalent scores.

Primary quality gates: net paired hit delta at least−1/192, with wins/losses separately; paired percentile bootstrap95%CI lower bound for ΔMRR at least−0.01, seed42 and10000 resamples. Guards40: net hit loss0 and mean ΔMRR at least−0.01, exploratory. The live latency gate is at least15% reduction in full-rerank p95, not retry HTTP latency.

## Offline192 screening

Exact recorded baseline parity passed192/192 for requests, complete outputs, features and recomputed meta predictions before frozen-policy screening. The first parity attempt failed honestly on tuple/list representation; canonical JSON comparison fixed representation only, without numerical tolerance. Failed evidence was retained. Final runtime6.003s;12 narrow tests passed at this stage.

| Policy | Net hit delta | ΔMRR | Primary95%CI | Result |
|---|---:|---:|---|---|
| N | 0 | −0.004464286 | [−0.013392857;0] | MRR gate fails |
| S | 0 | 0 | [0;0] | Conditional gates pass |
| C | 0 | 0 | [0;0] | Conditional gates pass |

All hit wins/losses0/0; guards40 unchanged. Retry documents A1061/N0/S347/C347; characters A2519328/N0/S881555/C881688. S/C retry on98 queries versus A121. S/C differ on62 cases, share213 selected documents, and have no character mismatch above5%. **Evidence selection superiority over random was not established.** No offline latency was simulated. The179-dependent-component sensitivity supports the no-retry direction, not independent validation.

## Bounded live batch-sensitivity smoke

The first12 eligible IDs from the original schedule were frozen without labels/outcomes: nonempty S retry and a proper baseline subset. Six balanced A/S/C permutations repeated twice. First scores stayed frozen; only retry requests were live, then production downstream was recomputed.30s request timeout,590s alarm within600s; no service starts or configuration changes.

- `live-smoke/`: blocked before POST,0/12 cases and0/36 requests,2.092s. Metadata differed only in `data[0].created` (1788617350→1788622626).15 tests and12/12 recorded parity passed.
- Parent then explicitly allowed only `data[*].created` runtime-instance drift. Original metadata retained; every other metadata field and357 local/config/model hashes remained strict. Timestamp-only acceptance and model-ID/other-field/hash rejection tests were added.
- `live-smoke-attempt-2/`: blocked before POST on integer/string schedule-key serialization,1.111s. Canonical JSON representation correction preserved IDs, policies and ordering; no numerical weakening.
- `live-smoke-attempt-3/`:12/12 cases,36/36 requests,0 errors/timeouts,31.708s;28 tests passed first. Recorded/fresh A drift78/149 scores, mean absolute0.0001412403/max0.0015124083. Fresh S/A common-document drift28/45, mean0.0002174572/max0.0015124083; C/A23/45, mean0.0002814042/max0.0025170445. All measured paired quality deltas0, CI[0;0], wins/losses0/0.

Retry HTTP p50/p95 seconds: A1.56855/2.22987, S0.40619/0.90828, C0.43155/1.17693. Documents149/45/45; characters339650/112185/112159. These are **not whole-rerank or E2E measurements**; the15% full-rerank gate cannot be transferred to them. Smoke established feasibility only, not safety or model equivalence.

## Fixed-pool LIVE192 A versus S

Parent authorized fresh first CE scores independently for **each arm**, fresh production A retries and S selection on its own fresh eligibility. Saved candidate pools/content/fan-in are shared; retrieval is not refreshed. The selective adapter changes only the second-pass seam, not first-stage processing, score adjustments, meta-ranking or preservation. No expensive live C campaign was run.

Original192 manifest cases/labels/order were retained (96 AS/96 SA). Runner/tests/policies/source hashes were frozen before results. Sequential existing-service requests;60/30s first/retry timeouts;4170s inference cutoff within4200s total; checkpoints every pair, ETA every12. First2 pairs were smoke-checked before continuing and not repeated.

34 narrow tests passed before live. Recorded adapter and actual-production parity192/192 passed before launch; fresh A production replay192/192 passed during the run, and later network-denied S replay192/192 verified complete outputs/features/predictions.357 recorded hashes were strict before/after, with only authorized timestamp drift1788617350→1788623070. A local GGUF hash **does not prove the mapping to actually loaded model weights**.

Completed192/192 pairs,603/603 requests,0 errors/timeouts; runtime1164.089s,1166.335s including archive. Each arm's measured rerank wall time includes fresh first pass, selection, second pass, adjustments, meta-ranking and preservation. Identical setup procedure is timed separately; checkpoints/setup are outside the rerank endpoint. This is a **fixed-pool rerank benchmark, not fresh retrieval or E2E latency**.

| Metric | A | S | Paired result |
|---|---:|---:|---|
| Hit@10 | 0.875 | 0.875 | Δ0; wins/losses0/0 |
| MRR@10 | 0.7922453704 | 0.7922453704 | Δ0;95%CI[0;0] |
| Macro recall@10 | 0.8503472222 | 0.8503472222 | Δ0;95%CI[0;0] |
| Rerank p50 seconds | 2.762329 | 2.554250 | Descriptive |
| Rerank p95 seconds | 5.2799443794 | 3.6086237151 | **31.654% latency reduction** |
| Retry documents | 1061 | 347 | Not token counts |
| Retry characters | 2519328 | 881555 | Not equal compute |

The reduction is `1 − p95(S)/p95(A) = 0.3165413391`; it is not a31.65% reciprocal speedup. The corresponding p95 latency ratio `p95(A)/p95(S)` is approximately1.463, not an E2E throughput measurement. Historical artifact field `p95_speedup` names the **latency reduction** quantity. Descriptive paired-bootstrap95%CI for that reduction is[0.231832975;0.358184166].

All prespecified gates pass on this endpoint/sample. Guards40 hit0.825, MRR0.8125, macro recall0.816666667 for both arms, all paired deltas0. Guards are cases with `mech` labels and no `where` labels, evaluated against `mech` labels; the `added_guard` flag alone selects34, not this40-case slice. Other retained slices: WHERE78, novel95, mechanical118, dedup191, no-glob190 and retry buckets71/70/26/25. All reported slice hit/MRR/recall deltas are0; overlapping slices must not be added.

Fresh scores are not identical: A first differs from recorded700/6528 (max absolute0.0027965903); A retry89/1061 (max0.0013829619). A/S first drift1020/6528 (max0.0032330751), common retry200/347 (max0.0021200180). Eligibility did not change; A/S outputs differ on17 cases, features153 and predictions96 despite equal aggregate quality. No materiality threshold was introduced after observing results.

## Commands and retained evidence

The following exact commands are recorded in execution history; they are historical, **not rerun during the documentation repair**. Working directory: `/Users/iurii.medvedev/Work/code-diver`.

```sh
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_research_selective_second_pass.py --tb=short
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_research_selective_second_pass.py --tb=short && git diff --check && PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/research_selective_second_pass.py --live192 --live-attempt live192-attempt-1
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python artifacts/research/2026-09-05/selective-second-pass/validate_live192.py
```

The first standalone narrow test command returned34 passed in4.13s; the combined pre-live command returned34 passed in3.69s. Exact earlier offline/smoke shell invocations were not recoverable from the surviving report; stage outcomes and attempt artifacts above are retained rather than fabricating command history.

Evidence root: `artifacts/research/2026-09-05/selective-second-pass/`. Final offline evidence: `verified/` (196 hashed JSON payloads); smoke directories above retain27 hashed payloads across all three attempts. LIVE192: `live192-attempt-1/` with manifest, checkpoint, raw pair requests/responses, metadata comparison, summary and203 hashed payloads. Supplemental internal validation: `live192-attempt-1-validation.json` and `validate_live192.py`; this is distinct from subsequent independent QA.

Archive: `live192-attempt-1.tar.gz`,14151588 bytes,204 files previously verified. SHA256: `e939f533cf7c798e5c271ffcf531b13dccb294390394ebf7a0c99b641f14e76f`. Archive hash index SHA256: `1b927df6a5d73db33106e789d39f88f8e8cfc0d3fc024af43d4c252375ef21b1`. Frozen runner SHA256: `158962916bda2a6b94fde2134beacde2bfa03c74d7a2b55f05a28b9c689c15db`. Earlier evidence was not deleted. Durable transfer remains the parent's responsibility.

## Post-QA documentation integrity review

The session counterpart remained intact. The report was reconstructed above while preserving the QA appendix below. Archive SHA256 was freshly recomputed and exactly matches the stated hash. A separate read-only standard-library calculation, without importing the research runner or using summary metrics, read `checkpoint.json` pairs and manifest labels:192 unique complete pairs,603 calls,0 recorded failures; retry document/character counts and all192/guards40 hit/MRR/macro-recall values match the tables above. Linear-interpolated95th percentiles calculated directly from raw `rerank_seconds` reproduce5.27994437944144 and3.608623715082649 seconds. Every all192 paired quality difference is zero, hence its empirical paired-bootstrap interval is necessarily[0;0]; this is not a safety proof. An initial diagnostic used `added_guard` and selected34; it was corrected to the prespecified40-case label-based definition before reporting guard results. No tests, experiments, replay or service calls were rerun for this review.

## Limitations and decision boundary

Dataset192 is dependent, label-informed and not independent validation; zero empirical CIs do not establish universal noninferiority. Fixed-pool results do not establish fresh retrieval/E2E gains. Random superiority remains unproven: S and C tied in offline/smoke quality and C was not evaluated in LIVE192. Batch-dependent scores, observed baseline drift and unproven loaded-model mapping remain explicit limitations. No policies were tuned after outcomes. No production/champion/services changes or promotion; parent decides the next gate after JOIN.

---

# Research QA Appendix: Selective Second Pass (2026-09-05)

## Verification Summary
Independent verification of the `selective-second-pass` research conducted on 2026-09-05.

### Test Execution
- Total tests run: 69
- Status: **PASSED**
- Components:
    - `test_research_selective_second_pass.py`: Basic policy, eligibility, and merge logic.
    - `test_research_large_search_eval.py`: Integration and parity against production baseline.
    - `test_research_ce_evidence.py`: Cross-encoder evidence extraction boundaries.
    - `test_research_candidate_budget.py`: Budgeting and cap enforcement.
    - `test_research_latency_independence.py`: Timing and order-independence validation.

### Metrics Validation (LIVE192)
Verification of `artifacts/research/2026-09-05/selective-second-pass/live192-attempt-1/summary.json` against independent offline calculations:

| Metric | Reported | Verified | Status |
|---|---|---|---|
| Complete Pairs | 192 | 192 | OK |
| Total Call Count | 603 | 603 | OK |
| Errors | 0 | 0 | OK |
| Quality Delta (Hit@10) | 0.0 | 0.0 | OK |
| P95 Latency (Baseline) | 5.2799s | 5.2799s | OK |
| P95 Latency (Selective) | 3.6086s | 3.6086s | OK |
| Latency Improvement | -31.654% | -31.654% | OK |
| Second-Pass Doc Counts | 1061 -> 347 | 1061 -> 347 | OK |

### Key Findings
- **Quality Preservation**: The selective second pass maintains 100% parity in ranking quality (Hit@10, MRR, Recall) relative to the full second pass on the 192-pair dataset.
- **Latency Gain**: Achieved a ~31.7% reduction in P95 latency by reducing second-pass document evaluation from 1061 to 347 documents.
- **Structural Integrity**: Preflight checks confirm hash parity and policy adherence. No network leakage detected during offline screening.

### Limitations
- Evaluated on fixed-pool 192 only.
- No E2E superior performance over random baseline established yet.
- Not yet promoted to production default.
