# H7 Local Gated Rerank - 2026-06-08

## Purpose

This follow-up corrects the direction of H7.3/H7.4 work: the gate should be
validated against local rerankers, not only Gemini Lite.

The tested question:

```text
Can local Gemma rerankers improve H7 if we call them only on low-confidence
cases?
```

No new API calls were made for this pass. The analysis uses saved local Gemma
rerank reports and the same gate simulator used for the Gemini reference.

## Inputs

Baseline:

- H7/H6.1 static local candidate ranking from the Gemma rerank matrix reports;
- EmbeddingGemma-300M file-level index;
- no code-body vectors;
- calibrated H6.1 weights.

Local rerankers:

- Gemma 4 E2B base-prior rerank;
- Gemma 4 E4B base-prior rerank;
- Gemma 4 12B base-prior rerank.

Reports:

- `.code-diver/reports/gemma4-rerank-matrix-200.json`;
- `.code-diver/reports/gemma4-12b-rerank-200.json`;
- generated gate reports:
  `.code-diver/reports/h7-local-gate-gemma4-*-seed*-train120-val40-test40.json`.

## Full 200-Case Local Rerank Baselines

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H7/H6.1 static | 200 | 0.800 | 0.935 | 0.970 | 0.975 | 0.870 | 0.896 | 872 |
| Gemma 4 E2B base-prior rerank | 200 | 0.795 | 0.935 | 0.965 | 0.975 | 0.867 | 0.894 | 3946 |
| Gemma 4 E4B base-prior rerank | 200 | 0.810 | 0.940 | 0.970 | 0.975 | 0.876 | 0.901 | 8819 |
| Gemma 4 12B base-prior rerank | 200 | 0.815 | 0.960 | 0.970 | 0.980 | 0.886 | 0.910 | 36791 |

Interpretation:

- E2B does not beat H7 overall.
- E4B beats H7 slightly, but the latency multiplier is about `10x`.
- 12B is the best local reranker by quality, but the latency multiplier is
  about `43x`.

## Gated Results

Each row below is a 120/40/40 split. Cost is zero because all rerankers are
local; latency is the relevant price.

### Gemma 4 E2B

| Seed | Policy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Call rate | Mean ms |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 17 | H7 only | 0.675 | 0.900 | 0.950 | 0.950 | 0.797 | 0.836 | 0.000 | 872 |
| 17 | E2B always | 0.675 | 0.850 | 0.950 | 0.950 | 0.785 | 0.826 | 1.000 | 3946 |
| 17 | E2B oracle gate | 0.675 | 0.900 | 0.950 | 0.950 | 0.797 | 0.836 | 0.000 | 872 |
| 23 | H7 only | 0.825 | 0.925 | 0.950 | 0.950 | 0.881 | 0.899 | 0.000 | 872 |
| 23 | E2B always | 0.825 | 0.950 | 0.950 | 0.950 | 0.883 | 0.901 | 1.000 | 3946 |
| 23 | E2B oracle gate | 0.825 | 0.950 | 0.950 | 0.950 | 0.883 | 0.901 | 0.025 | 949 |
| 42 | H7 only | 0.850 | 0.925 | 0.925 | 0.925 | 0.879 | 0.891 | 0.000 | 872 |
| 42 | E2B always | 0.850 | 0.900 | 0.925 | 0.925 | 0.880 | 0.891 | 1.000 | 3946 |
| 42 | E2B oracle gate | 0.850 | 0.925 | 0.925 | 0.925 | 0.883 | 0.894 | 0.025 | 949 |

Decision: E2B is not a good reranker candidate. Keep it for explanation/Judge
experiments if useful, not H7 reranking.

### Gemma 4 E4B

| Seed | Policy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Call rate | Mean ms |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 17 | H7 only | 0.675 | 0.900 | 0.950 | 0.950 | 0.797 | 0.836 | 0.000 | 872 |
| 17 | E4B always | 0.675 | 0.900 | 0.950 | 0.950 | 0.797 | 0.836 | 1.000 | 8819 |
| 17 | E4B oracle gate | 0.675 | 0.900 | 0.950 | 0.950 | 0.797 | 0.836 | 0.000 | 872 |
| 23 | H7 only | 0.825 | 0.925 | 0.950 | 0.950 | 0.881 | 0.899 | 0.000 | 872 |
| 23 | E4B always | 0.850 | 0.950 | 0.950 | 0.950 | 0.892 | 0.907 | 1.000 | 8819 |
| 23 | E4B oracle gate | 0.850 | 0.950 | 0.950 | 0.950 | 0.896 | 0.910 | 0.050 | 1270 |
| 42 | H7 only | 0.850 | 0.925 | 0.925 | 0.925 | 0.879 | 0.891 | 0.000 | 872 |
| 42 | E4B always | 0.875 | 0.925 | 0.925 | 0.925 | 0.892 | 0.900 | 1.000 | 8819 |
| 42 | E4B oracle gate | 0.875 | 0.925 | 0.925 | 0.925 | 0.892 | 0.900 | 0.025 | 1071 |

Decision: E4B has real but sparse rerank signal. It is not viable always-on,
but it can be a local gated candidate if we can identify the `2.5-5%` useful
queries.

### Gemma 4 12B

| Seed | Policy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Call rate | Mean ms |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 17 | H7 only | 0.675 | 0.900 | 0.950 | 0.950 | 0.797 | 0.836 | 0.000 | 856 |
| 17 | 12B always | 0.675 | 0.925 | 0.950 | 0.950 | 0.806 | 0.843 | 1.000 | 36791 |
| 17 | 12B oracle gate | 0.675 | 0.925 | 0.950 | 0.950 | 0.806 | 0.843 | 0.050 | 2652 |
| 23 | H7 only | 0.825 | 0.925 | 0.950 | 0.950 | 0.881 | 0.899 | 0.000 | 856 |
| 23 | 12B always | 0.875 | 0.950 | 0.950 | 0.950 | 0.912 | 0.922 | 1.000 | 36791 |
| 23 | 12B oracle gate | 0.875 | 0.950 | 0.950 | 0.950 | 0.912 | 0.922 | 0.050 | 2652 |
| 42 | H7 only | 0.850 | 0.925 | 0.925 | 0.925 | 0.879 | 0.891 | 0.000 | 856 |
| 42 | 12B always | 0.875 | 0.925 | 0.925 | 0.925 | 0.900 | 0.907 | 1.000 | 36791 |
| 42 | 12B oracle gate | 0.875 | 0.925 | 0.925 | 0.925 | 0.900 | 0.907 | 0.050 | 2652 |

Decision: 12B is the strongest local reranker in this slice, but only if gated
extremely hard. Always-on 12B is too slow for interactive search.

## Current Local-Only Conclusion

The local-only reranker story is:

1. H7/H6.1 static search remains the default local fast path.
2. Gemma E2B is not a useful H7 reranker.
3. Gemma E4B is a sparse local reranker: keep as active, but gated only.
4. Gemma 12B is the strongest local reranker by quality, but must be called on
   about `2.5-5%` of queries to be acceptable.
5. The most valuable next local model is not another generative Gemma loop; it
   is a true local cross-encoder reranker such as Qwen3-Reranker served through
   a real rerank endpoint.

## Next Local Hypotheses

| ID | Hypothesis | Why |
| --- | --- | --- |
| `H7.6-local-ce` | Qwen3-Reranker cross-encoder inside the H7 gate. | Purpose-trained reranker should be faster and more reliable than generative Gemma listwise prompting. |
| `H7.6-e4b-gated` | Gemma E4B only for low-confidence route/score-shape cases. | E4B has sparse signal and much lower latency than 12B. |
| `H7.6-12b-oracle-distill` | Use 12B decisions to train a smaller gate/reranker, then do not call 12B live. | 12B is too slow, but its corrections can become training labels. |
| `H7.6-local-monotonic` | Enforce monotonic top-k preservation for all local rerankers. | Old agentic local reports demoted good H7 candidates and dropped Hit@10. |
