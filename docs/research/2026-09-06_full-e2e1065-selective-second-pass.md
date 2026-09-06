# Full E2E 1065: Selective Second Pass — Complete Results

## Summary
Completed **1065/1065 paired A/S comparisons** (extension-repair-01, parent attempt-04). **0 errors**.

## Quality Metrics (N=1065)

| Slice | Metric | A (H91a) | S (Selective) | Delta | 95% CI |
|---|---|---|---|---|---|
| **full1065** | hit@10 | 0.86854 | 0.86854 | 0.0 | [0.0, 0.0] |
| | MRR@10 | 0.83626 | 0.83665 | +0.00039 | [-0.0003, +0.0016] |
| | recall@10 | 0.86066 | 0.86066 | 0.0 | [0.0, 0.0] |
| **WHERE78** | hit@10 | 0.87179 | 0.87179 | 0.0 | [0.0, 0.0] |
| | MRR@10 | 0.70655 | 0.70655 | 0.0 | [0.0, 0.0] |
| | recall@10 | 0.81859 | 0.81859 | 0.0 | [0.0, 0.0] |
| **mech229** | hit@10 | 0.86463 | 0.86463 | 0.0 | [0.0, 0.0] |
| | MRR@10 | 0.79961 | 0.79961 | 0.0 | [0.0, 0.0] |
| | recall@10 | 0.86066 | 0.86066 | 0.0 | [0.0, 0.0] |

## Latency (N=1065)

| Metric | A (H91a) | S (Selective) | Delta |
|---|---|---|---|
| E2E p50 | 11.42s | 10.58s | **−0.84s (−7.4%)** |
| E2E p95 | 30.44s | 32.00s | +1.56s (+5.1%) |
| Rerank p50 | 5.32s | 4.10s | **−1.22s (−22.9%)** |
| Rerank p95 | 11.00s | 8.82s | **−2.18s (−19.8%)** |
| Retrieval p50 | 5.30s | 5.32s | +0.02s |
| Retrieval p95 | 25.49s | 28.97s | +3.48s |

**p95 delta CI**: [−3.19s, +11.10s] — includes 0, no statistical significance.

## Resource Usage

| Resource | A (H91a) | S (Selective) | Reduction |
|---|---|---|---|
| Retry documents | 8172 | 2614 | **−68.0%** |
| Retry chars | 19,097,075 | 6,642,971 | **−65.2%** |

## Decision
**INCONCLUSIVE / NO PROMOTION.** Quality is identical, rerank latency is ~20% faster (p95), but E2E p95 CI includes zero. The selective second pass is **safe** (no quality regression) and **more efficient** (68% fewer retries), but the E2E latency benefit is masked by retrieval variance. No promotion or equivalence claims.

## Commands
All commands from project root with `.venv/bin/python`:
```bash
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

# Smoke
.venv/bin/python scripts/research_full_e2e1065_selective_second_pass.py smoke \
  --attempt extension-repair-01 --parent-attempt attempt-04 \
  --budget-seconds 10800 --rerank-url http://localhost:18081/v1/rerank

# Run (repeat with --resume --max-pairs 64 at segment_boundary)
.venv/bin/python scripts/research_full_e2e1065_selective_second_pass.py run \
  --attempt extension-repair-01 --parent-attempt attempt-04 \
  --budget-seconds 10800 --rerank-url http://localhost:18081/v1/rerank \
  --resume --max-pairs 64

# Summary
.venv/bin/python scripts/research_full_e2e1065_selective_second_pass.py summary \
  --attempt extension-repair-01 --parent-attempt attempt-04
```

## Artifacts
- `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/attempt-04/` — parent (782 pairs, hard_cap)
- `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/extension-repair-01/` — extension (283 new pairs, 1065 total)
- `artifacts/research/2026-09-05/full-e2e1065-selective-second-pass/server-repair/` — CE capacity fix evidence

## Limitations
- Runtime continuity between parent and extension is unknown (separate budgets, server instances)
- Independent holdout NOT certified (same dataset, same split)
- CE server context was 40960 (not 8192 as in manifest) for both A and S