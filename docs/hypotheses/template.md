# Hypothesis Documentation Template

Use this template for every indexing, retrieval, ranking, or benchmark scenario that is meant to be compared across runs. Keep exact metrics out unless they are present in a saved report, trace, config, or local doc. Use `not measured` for missing values.

## Summary Row

| Field | Value |
| --- | --- |
| ID | `H?` |
| Title |  |
| Status | proposed / active / accepted / rejected / superseded / invalid |
| One-line decision |  |
| Primary evidence |  |

## Detail

| Field | Notes |
| --- | --- |
| ID | Stable identifier. Prefer existing names such as `H1`, `H2A`, `H3`, `H5`, or config hypothesis names. |
| Title | Short human-readable name. |
| Status | `accepted`, `active`, `rejected`, `superseded`, `invalid`, or `proposed`. |
| Motivation | What retrieval failure or product constraint this tests. |
| Assumptions | Conditions that must be true for the hypothesis to win. |
| Index composition | Persistent and temporary item types, vector dimensions, graph artifacts, payload size, and index size. |
| Search/ranking flow | Ordered pipeline from query to returned results. |
| Model/provider matrix | Embedding providers, rerankers, generation models, local/API split, and runtime notes. |
| Dataset | Dataset path or benchmark profile, case count, label shape, and caveats. |
| Metrics | Hit@k, file Hit@k, MRR, nDCG, MAP, precision/recall, CI, and validity status. |
| Cost/latency/index-size | Mean/p95 latency, token/cost estimates, persistent storage, temporary vector count, and build time. |
| Result summary | Short factual readout of what happened. |
| Decision | Keep, reject, rerun, narrow, or promote. Include why. |
| Failure modes | What can make the run misleading or poor: candidate recall, reranker demotion, auth failures, label leakage, prompt protocol errors, unstable tie-breaking. |
| Follow-ups | Concrete next comparisons or missing validation. |
| Links | Local docs, configs, datasets, reports, traces, and scripts. |

## Markdown Skeleton

```markdown
## H? - Title

| Field | Value |
| --- | --- |
| ID | `H?` |
| Status | active |
| Motivation |  |
| Assumptions |  |
| Index composition |  |
| Search/ranking flow |  |
| Model/provider matrix |  |
| Dataset |  |
| Metrics | not measured |
| Cost/latency/index-size | not measured |
| Result summary | not measured |
| Decision |  |
| Failure modes |  |
| Follow-ups |  |
| Links |  |
```
