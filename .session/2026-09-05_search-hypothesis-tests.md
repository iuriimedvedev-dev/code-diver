# Search hypothesis tests — decisions and outcomes (2026-09-05)

## Decisions

- R1 selective second CE pass: **inconclusive**. The equal-budget control did not complete; do not promote the second pass.
- R2 query-relevant fragments: **promising but inconclusive**. Seven of eight pairs completed; WHERE hit@10 was `0.50→0.75` and MRR `0.15625→0.19792`, but three guard golds were absent from the pools and no general gain is proven.
- R3 candidate budget: **blocked for current H-91a**. The historical proxy rejects quota34 (`91/115→85/115`; holdout `32/36→33/36`); selector training is deferred.
- R4 latency: **partial / E2E unmeasured**. The model-only microbenchmark excludes prediction itself as an explanation for seconds of latency in the tested setup (default warm p50 `0.084 ms`, p95 `0.149 ms`), but does not reject the broader execution-overhead hypothesis. No threading change is justified; E2E remains unmeasured.
- Independence is **not certified**: reconstructed split `856/209`, `3` normalized-query overlaps, and `113` test cases share exact-answer families. This is an evaluation risk, not demonstrated leakage.

## Next

Freeze family-aware evaluation and provenance, add E2E stage instrumentation, complete adequately powered paired R2 and equal-budget R1, then capture wider current pools before selector training. Keep R1–R4 samples separate; do not recompute a combined score. Consolidated QA: `PYTHONPATH=src python3 -B -m pytest tests/test_research_ce_evidence.py tests/test_research_candidate_budget.py tests/test_research_latency_independence.py` — `21 passed in 0.67s`; `git diff --check` passed. Initial collection without `PYTHONPATH=src` failed (`ModuleNotFoundError: code_diver`); adding the source import path resolved it without code changes or installations. No benchmarks were repeated; only these three coordination documents were edited, and pre-existing production/champion changes were left untouched.

## Preservation

Detailed evidence: `docs/research/2026-09-05_search-hypothesis-tests.md`; executor reports remain `docs/research/2026-09-05/ce-evidence.md`, `candidate-budget.md`, and `latency-independence.md`. Keep gitignored `artifacts/research/2026-09-05/` in an external retained bundle with recorded hashes; do not add large raw JSON, traces, or models to git.