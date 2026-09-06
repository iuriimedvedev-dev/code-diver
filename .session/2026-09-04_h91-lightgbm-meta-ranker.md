# H-91: LightGBM CE-stage meta-ranker

## Results
**H-91a — новый чемпион.** LightGBM LambdaRank на 16 фичах из CE-stage + fan-in + lexical + path.

### WHERE-78 (78 кейсов)
| Metric | H-89a (champion) | H-91a (meta-ranker) | Δ |
|---|---|---|---|
| hit@10 | 61/78 (78.2%) | **68/78 (87.2%)** | **+7** |
| recall@10 | 0.7085 | 0.8186 | +0.110 |
| MRR@10 | 0.3858 | 0.7066 | +0.321 |
| hit@1 | 18 (23.1%) | 49 (62.8%) | +31 |
| nDCG@10 | 0.4457 | 0.7097 | +0.264 |
| search_ms | 10797 | 11831 | +1034 |

### mech150 (229 cases) — regression guard
| Metric | H-89a | H-91a | Δ |
|---|---|---|---|
| hit@10 | 193/229 (84.3%) | **202/229 (88.2%)** | **+9** |
| recall@10 | 0.804 | 0.859 | +0.055 |
| MRR@10 | 0.615 | 0.817 | +0.202 |
| hit@1 | 112 (48.9%) | 179 (78.2%) | +67 |
| nDCG@10 | 0.634 | 0.806 | +0.172 |
| search_ms | 7265 | 12485 | +5220 |

## Key decisions
1. LightGBM LambdaRank (200 trees, leaf 64, lr 0.02) trained on 856 queries, tested on 209
2. Test NDCG@10: 0.811 vs base 0.704 (+15%)
3. Eager model load at construction time to avoid segfault
4. Pickle-based lexical index cache (2.1GB → 475MB, ~60s load)
5. Champion promoted to H-91a

## Next steps
1. Run 1065-case full validation on H-91a
2. Consider: cross-encoder fine-tuning instead of meta-ranker?
3. Seed generation improvement for remaining 10 misses
