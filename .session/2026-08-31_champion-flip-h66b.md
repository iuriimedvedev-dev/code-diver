# Decision: Champion Flip to H-66b
Date: 2026-08-31

## Context
The project has moved to a new champion configuration for IntelliJ Community repositories. The decision was made to prioritize the **WHERE** arm performance, which represents more realistic user-facing queries, over the strict **1065** recall gate.

## Metric Comparison

| Metric | Old Champion (H46) | New Champion (H66b) | Delta |
| --- | --- | --- | --- |
| **WHERE-79 Recall@10** | 0.503 | 0.5757-0.5905 | **+0.073** (approx) |
| **WHERE-79 MRR** | 0.285 | 0.3630-0.3708 | **+0.078** (approx) |
| **WHERE-79 Hit@1** | - | 0.2532 | - |
| **1065 Recall@10** | 0.8292 | 0.8175 | -0.0117 |
| **1065 Hit@1** | 0.6263 | 0.6376 | **+0.0113** |
| **Workflow Bucket** | - | 0.8027 | Best on record |

## Rationale for 1065 Gate Override
The 1065 recall regression (-0.0117) is considered acceptable because:
1. **WHERE slice priority**: The WHERE-79 dataset reflects more realistic user queries and shows a massive improvement (+0.073 recall).
2. **Precision improvement**: Hit@1 on 1065 actually improved (+0.0113).
3. **Workflow performance**: The workflow bucket performance (0.8027) is the best recorded to date.

## Recommended Profiles
- **Default Champion**: `configs/intellij/intellij-h66b-champion.yml` (Single-pass, fast).
- **Best Agentic/WHERE Profile**: `configs/intellij/intellij-h74-agentic-where.yml` (using `h75_fanout_champion_llmrerank_monotonic` / `h76_union_ce_q4`). This profile achieves WHERE 0.6116-0.6179 / MRR 0.3781-0.3812 but requires an LLM and adds 11-18.8s latency per query.

## Implementation Details
- New config file: `configs/intellij/intellij-h66b-champion.yml` (copy of `intellij-h66b-budget.yml` with updated metadata).
- Archived champion: `configs/intellij/intellij-h46-preserve-top.yml`.
- `CHANGELOG.md` updated with the promotion record.
