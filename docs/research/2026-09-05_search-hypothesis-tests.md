# Search hypothesis tests — consolidated evidence (2026-09-05)

## Scope and decision rule

This is a joined documentation layer over the three executor handoffs. Results remain in their original case sets and are not recomputed into one cross-experiment score. No production or champion configuration was changed, and no arm is promoted.

## R1 — selective second CE pass

**Rationale.** Re-scoring low first-pass candidates with up to `2400` content characters may recover evidence hidden by the `850`-character first pass. The tested policy was score `<0.3`, retry cap `24`, and merge by the maximum score.

**Control and acceptance.** Both arms used the same frozen 34-candidate pool. The intended control spent the same retry-count/base-rank budget; this is a budget-ceiling control, not exact token parity. Acceptance required paired recall/MRR improvement, no material guard regression, and latency by retry bucket, including zero-retry, provider-failure, and high-score-gold negatives.

**Outcome: INCONCLUSIVE.** Only one WHERE smoke pair completed: both arms had hit@10 `1`, MRR@10 `0.200`, and no rescue/regression. The equal-budget control was interrupted before a valid quality result, so the hypothesis is not accepted. Evidence and commands are in `docs/research/2026-09-05_ce-evidence.md`, especially commands 1–7, and `artifacts/research/2026-09-05/ce-evidence/` (`smoke-02`, `r2-eight`, `summary.json`).

## R2 — query-relevant fragments versus file beginning

**Rationale.** Query-token-matched source fragments may retain relevant declarations that a source head omits. This is an extractive proxy, not a query-aware semantic index and not the old H-62 proxy.

**Control and acceptance.** The same frozen 34 candidates and the same 850-character total document cap were used for head and fragment arms. Acceptance required strict exact-file improvement without guard-slice loss; source provenance and incomplete pairs had to remain visible.

**Outcome: PROMISING BUT INCONCLUSIVE.** Seven of eight pairs were complete. On WHERE, hit@10 improved `0.5000→0.7500` and MRR@10 `0.15625→0.19792`; one rescue and one ranking regression were observed. Three guard cases lacked an exact gold file in the candidate pool, so their zero/zero result cannot certify non-regression or a general win. The eighth pair was excluded from paired aggregates because the fragment batch did not complete. Evidence: `docs/research/2026-09-05_ce-evidence.md`, `artifacts/research/2026-09-05/ce-evidence/r2-eight/results.json`, and corrected `summary.json`.

## R3 — 34 candidates and a CE selector

**Rationale and acceptance.** A 34-candidate pool could be sufficient only if pool recall is not the bottleneck and CE34 remains non-inferior to deeper 60/80 pools at cuts 10/14/20 under the declared latency budget. Negative cases include absent gold, provider errors, and rank ties.

**Outcome: BLOCKED for current H-91a.** No audited, case-joined H-91a multi-probe export with depth-specific CE scores/features exists; current CE34/60/80 quality and latency are therefore unmeasured. A historical persisted LTR proxy was not substituted for the champion: fixed34 had WHERE `91/115` versus fixed60 `96/115` and fixed80 `98/115`. The predeclared quota34 selector was rejected by the proxy (`91/115→85/115`; holdout `32/36→33/36`), and selector training is deferred. Evidence: `docs/research/2026-09-05_candidate-budget.md`, commands 85–90, and `artifacts/research/2026-09-05/candidate-budget/`.

## R4 — cold/warm latency and LightGBM threads

**Rationale and acceptance.** Separating model load, first prediction, warm prediction, and end-to-end stages should prevent attributing service or retrieval startup to LightGBM. A thread setting would be accepted only if warm p95 improved without score drift, with E2E stage shares and service-warm/cold comparisons.

**Outcome: PARTIAL / E2E UNMEASURED.** The synthetic 34×16 model-only benchmark measured default warm prediction at p50 `0.084 ms` and p95 `0.149 ms`; no tested explicit thread setting improved warm p95, and score drift was zero on that synthetic input. This excludes prediction itself as an explanation for seconds of latency in the tested setup, but does not reject the broader execution-overhead hypothesis. E2E remains unmeasured: no stage shares or justified threading recommendation exists. Evidence: `docs/research/2026-09-05_latency-independence.md`, commands 9–15, and `artifacts/research/2026-09-05/latency-independence/` (`results.json`, `audit.json`).

## Independence and preservation

The audit reconstructed `856/209` train/test rows, found `3` normalized-query overlaps, and found `113` test cases sharing exact-answer families with reconstructed training rows. Missing feature dump, train IDs, corpus snapshot, and model provenance mean leakage is **not demonstrated**, but evaluation independence is not certified. Consolidated QA: `PYTHONPATH=src python3 -B -m pytest tests/test_research_ce_evidence.py tests/test_research_candidate_budget.py tests/test_research_latency_independence.py` — `21 passed in 0.67s`; `git diff --check` passed. The initial invocation without `PYTHONPATH=src` failed collection with `ModuleNotFoundError: code_diver`; no code changes or installations were needed. No benchmarks were repeated.

Next priority is to freeze family-aware evaluation and provenance, instrument E2E stages, complete a powered paired R2 and equal-budget R1, then capture wider current pools before selector training. Research outputs under `artifacts/research/2026-09-05/` are gitignored: preserve them in an external run bundle or explicitly retained artifact archive with the recorded hashes; do not add large JSON/trace/model files to git. Keep raw reports and corrected summaries together, and do not mix samples or recompute a cross-experiment score.