# Quality, Latency, And Cost Tradeoff - 2026-06-08

## Question

Search quality metrics are not enough. A ranker that adds a few Hit@1 points but
triples latency or burns API spend may be the wrong product default.

This report compares the current CodeSearchNet Python 1,000-case runs by:

- quality: Hit@1/3/5/10, MRR, nDCG;
- latency: mean and p95 search time;
- API cost: trace-derived token/cost usage where available;
- footprint: persistent index size where comparable.

## Main Table

All rows use the same local-positive CodeSearchNet/MTEB Python 1,000 slice.
API cost is actual trace-derived estimated cost when `llm_rerank_response` usage
events exist. Local deterministic rows have `$0` API cost, but still consume local
CPU/GPU time.

| Run | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR | nDCG | Mean ms | P95 ms | API $/1k | Tokens/1k | nDCG/sec | Hit@1/sec |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H6 baseline | 0.856 | 0.960 | 0.982 | 0.987 | 0.909 | 0.929 | 3145.7 | 3752.3 | 0.0000 | 0 | 0.295 | 0.272 |
| H7 API manifest | 0.858 | 0.956 | 0.977 | 0.987 | 0.911 | 0.930 | 1609.7 | 1698.9 | 0.0000 | 0 | 0.578 | 0.533 |
| H7 query expansion | 0.857 | 0.957 | 0.980 | 0.987 | 0.909 | 0.928 | 780.2 | 851.0 | 0.0000 | 0 | 1.190 | 1.098 |
| H9.1 body evidence | 0.853 | 0.947 | 0.974 | 0.985 | 0.907 | 0.927 | 1609.1 | 1708.1 | 0.0000 | 0 | 0.576 | 0.530 |
| H9.2 bounded body evidence | 0.860 | 0.956 | 0.977 | 0.986 | 0.912 | 0.930 | 1600.7 | 1683.8 | 0.0000 | 0 | 0.581 | 0.537 |
| Gemini Lite rerank | 0.911 | 0.978 | 0.988 | 0.989 | 0.944 | 0.956 | 3487.8 | 5224.6 | 2.9333 | 11,753,516 | 0.274 | 0.261 |

## Incremental Tradeoffs

Use H7 query expansion as the current fast local baseline because it is the best
latency/quality balance in this table.

| Candidate | Delta Hit@1 vs H7 QE | Delta Hit@10 vs H7 QE | Extra mean latency | Extra API $/1k | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| H9.2 bounded body evidence | +0.003 | -0.001 | +820.5 ms | $0.0000 | Not worth it as always-on: only +3 top-1 wins per 1,000 queries and loses one top-10 hit. |
| Gemini Lite rerank | +0.054 | +0.002 | +2707.6 ms | $2.9333 | Quality mode candidate: about +54 top-1 wins per 1,000 queries, but much slower and nonzero API spend. |

Cost per additional top-1 success for Gemini Lite versus H7 query expansion:

```text
$2.9333 per 1,000 queries / 54 extra top-1 successes ~= $0.054 per extra top-1 success
```

Latency per additional top-1 success is less attractive:

```text
+2707.6 ms per query * 1,000 queries / 54 extra top-1 successes ~= 50.1 seconds of extra waiting per extra top-1 success
```

That makes Gemini Lite reasonable for batch/high-quality mode and questionable
for every interactive query unless we add confidence gating.

## Footprint

Observed JSON index artifact sizes on the Python 1,000 local-positive slice:

| Index | Size | Notes |
| --- | ---: | --- |
| H6/H5 EmbeddingGemma file locator | 46 MB | `file_summary + file_manifest` |
| H7 API manifest | 69 MB | Adds `file_api_manifest` |
| H9 body evidence | 69 MB | Adds `file_body_evidence` |
| H9 graph artifact | 3.6 MB | Containment graph |

H7/H9 both add roughly 50% more vector records than H6. H9 did not produce enough
quality gain to justify this as an always-on index lane.

## Decision

Current recommendations:

| Mode | Recommended setup | Why |
| --- | --- | --- |
| Fast local default | H7 query expansion over H6 file locator | Best nDCG/sec and Hit@1/sec, no API cost. |
| Quality mode | H6/H7 candidates + Gemini 3.1 Flash Lite rerank | Best measured quality, acceptable API cost for deliberate/high-quality runs. |
| Research only | H9 body evidence | Sparse complementary signal, but poor global tradeoff. Needs gating and richer calibration. |

The next useful experiment is not “add one more lane everywhere”. It is a
cost-aware policy:

1. Run fast H7 query expansion first.
2. If top scores/margins look confident, stop.
3. If confidence is low, run Gemini Lite or a local cross-encoder on top-N.
4. Only run body-evidence fallback for semantic/comment/string-heavy queries.

## Gaps

- Current search reports do not persist token/cost usage into top-level metrics.
  I recovered Gemini Lite cost from trace events.
- Local compute cost is represented as latency only, not energy or amortized
  hardware cost.
- Timing rows came from separate runs, so use them as practical measurements, not
  microbenchmark-perfect comparisons.
