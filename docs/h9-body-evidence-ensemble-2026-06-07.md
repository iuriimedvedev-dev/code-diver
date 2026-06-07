# H9 Body-Evidence And Reranker Ensemble - 2026-06-07

## Question

Can we improve the calibrated hybrid rerank setup by adding a third compact
file-level index lane that stores body evidence: comments, string literals,
return/raise/control lines, and effect-heavy lines?

This tests the user-proposed direction directly: combine several search outputs
with weights/meta-rankers instead of trusting one vector search.

## Implementation

| Component | Value |
| --- | --- |
| Builder | `FileBodyEvidenceItemBuilder` |
| Index kind | `file_body_evidence` |
| Config flag | `scanner.file_body_evidence_chunks` |
| Persistent shape | One extra file-level item per file, no full code-body vectors |
| Main configs | `configs/benchmarks/codesearchnet-h9-body-evidence-embeddinggemma-1000.yml`, `configs/benchmarks/codesearchnet-h9-body-evidence-bounded-embeddinggemma-1000.yml` |

The indexed text is intentionally compact. It captures body-derived evidence but
does not embed complete code bodies.

## CodeSearchNet Python 1000

All rows use the same 1,000-case public local-positive CodeSearchNet/MTEB Python
slice and EmbeddingGemma-300M for local embeddings unless noted.

| Run | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Precision@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H6 baseline | 0.856 | 0.960 | 0.982 | 0.987 | 0.909 | 0.929 | 0.152 | 3145.7 |
| H7 API manifest | 0.858 | 0.956 | 0.977 | 0.987 | 0.911 | 0.930 | 0.226 | 1609.7 |
| H7 query expansion | 0.857 | 0.957 | 0.980 | 0.987 | 0.909 | 0.928 | 0.152 | 780.2 |
| H9.1 body evidence | 0.853 | 0.947 | 0.974 | 0.985 | 0.907 | 0.927 | 0.235 | 1609.1 |
| H9.2 bounded body evidence | 0.860 | 0.956 | 0.977 | 0.986 | 0.912 | 0.930 | 0.229 | 1600.7 |
| Gemini Lite rerank | 0.911 | 0.978 | 0.988 | 0.989 | 0.944 | 0.956 | 0.155 | 3487.8 |

H9.2 improves Hit@1 slightly versus deterministic H6/H7 but loses Hit@3/5/10
and does not approach Gemini Lite. The effect is too small to promote.

Per-case delta against H7 query expansion:

| Outcome | Cases |
| --- | ---: |
| H9.2 better rank | 34 |
| H9.2 worse rank | 23 |
| Same rank | 943 |

This means body evidence has complementary signal, but it is sparse and unsafe
to blend globally.

## Ensemble Results

Train/test split:

- train: first 900 common cases;
- test: next 100 common cases;
- no API calls in ensemble analysis;
- input rankers: H6, H7 API, H7 query expansion, H9.1, H9.2.

| Method | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Best single deterministic: H7 query expansion | 0.940 | 0.980 | 0.980 | 1.000 | 0.959 | 0.969 | Baseline winner |
| Best RRF including H9 | 0.930 | 0.980 | 0.990 | 1.000 | 0.956 | 0.967 | Below best single |
| Meta-ranker including H9 | 0.920 | 0.980 | 0.990 | 1.000 | 0.951 | 0.963 | Worse |
| Pairwise meta-ranker including H9 | 0.920 | 0.980 | 0.990 | 1.000 | 0.951 | 0.963 | Worse |
| Oracle best-rank | 0.940 | 0.980 | 0.990 | 1.000 | n/a | n/a | Label-leak upper bound |

Adding Gemini Lite:

| Method | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Single Gemini Lite | 0.960 | 0.990 | 1.000 | 1.000 | 0.978 | 0.983 | Winner |
| Best RRF with Gemini + H9 | 0.950 | 0.980 | 1.000 | 1.000 | 0.969 | 0.977 | Demotes Gemini |
| Meta-ranker with Gemini + H9 | 0.950 | 0.990 | 1.000 | 1.000 | 0.970 | 0.978 | Below Gemini |
| Oracle best-rank with Gemini + H9 | 0.980 | 0.990 | 1.000 | 1.000 | n/a | n/a | Headroom only |

Rank-position-only ensembles still cannot beat the best single Gemini Lite
reranker. The oracle shows remaining headroom, but the current features do not
identify safe overrides.

## SWEbenchCodeRetrieval 100 Smoke

| Run | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Precision@10 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H6 baseline | 0.610 | 0.810 | 0.920 | 0.960 | 0.752 | 0.804 | 0.185 | 776.1 |
| H9 body evidence | 0.610 | 0.790 | 0.870 | 0.940 | 0.748 | 0.796 | 0.248 | 238.8 |

H9 does not transfer as a quality improvement to SWEbench. It keeps Hit@1 flat
and loses recall at Hit@3/5/10.

## Decision

Reject H9 as an always-on default.

Keep the implementation and configs as a research lane because H9.2 improves 34
individual CodeSearchNet cases and provides a useful negative result: adding a
body-derived file-level vector is not enough by itself. The next version should
not globally fuse H9. It should be gated:

- run body-evidence only for low-confidence semantic queries;
- use score margins and route features before allowing body evidence to override
  H6/H7/Gemini;
- train on raw hybrid scores, LLM confidence, and cross-encoder scores, not only
  final rank positions.

Cost/latency conclusion: H9.2 adds about `+820 ms/query` versus the fast H7
query-expansion baseline while gaining only `+0.003` Hit@1 and losing `-0.001`
Hit@10. See the broader tradeoff report:
[quality latency cost tradeoff](./quality-latency-cost-tradeoff-2026-06-08.md).

## Artifacts

| Artifact | Purpose |
| --- | --- |
| `.code-diver/reports/h9-body-evidence-embeddinggemma-codesearchnet-1000.json` | Full H9.1 CodeSearchNet report |
| `.code-diver/reports/h9-body-evidence-bounded-embeddinggemma-codesearchnet-1000.json` | Full H9.2 CodeSearchNet report |
| `.code-diver/reports/h9-reranker-ensemble-train900-test100.json` | Deterministic H6/H7/H9 ensemble |
| `.code-diver/reports/h9-reranker-ensemble-with-gemini-train900-test100.json` | H6/H7/H9 plus Gemini Lite ensemble |
| `.code-diver/reports/swebench-code-retrieval-100-h9-body-evidence-embeddinggemma.json` | SWEbench H9 smoke |
