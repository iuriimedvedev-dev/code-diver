# 2026-09-02 — remaining retrieval + agent eval

## Facts
- Pool ceiling recall@200 ≈ 0.923 (WHERE-79). recall@10 champion H-83 = 0.6444 (WHERE-78).
- jbcontext live FAST WHERE-78 = 0.7370 recall@10. Comparison is search-tool vs search-tool.
- Agent eval exists: `evaluate-search-tools`. Not used vs jbcontext.
- Do not retry: HyDE, H-84 v1 (post-CE RRF), H-81/H-82, fatter index, LTR.

## Work
1. H-84v2: `multi_query.union_rerank` — variants retrieve CE-less, RRF fuse, one CE. Arm yaml, default OFF.
2. H-86 agent yaml: H-74/H-75/H-76 hypotheses on H-83 champion search stack.
3. Eval WHERE-78: H-84v2 vs champion; agent arms h74/h75/h76 vs jbcontext search.

## Gate
Same-sitting WHERE-78. Promote only if where recall@10 up, no MRR collapse, latency honest.
Champion yaml not modified until a winner.
