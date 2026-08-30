# IntelliJ WHERE-79 — H-66 Budget Champion

Experiment wave, `n=79`. Champion `intellij-h46-preserve-top.yml` remains untouched.

## Baselines

- H52: recall@10 `0.5283`, MRR `0.2893`, hit@1 `0.1646`, ndcg `0.3233`
- H-57 (LLM blurbs): `0.5785` / `0.3368`
- jbcontext: `0.685` / `0.347`

## Results

- **H-66** — `intellij-h66-purpose-terms.yml`, collection `intellij_h66_purpose_terms_qwen`: deterministic `purpose:` line plus `terms:` camelCase/snake split, no LLM. `0.5483` / `0.3195` / hit@1 `0.1899` / ndcg `0.3641`. Reindex: 35 min, 136578 points.
- **H-66b — NEW BEST** — `intellij-h66b-budget.yml`, collection `intellij_h66b_budget_qwen`, scanner flag `file_summary_compact_budget: true`: purpose and terms first; shortened embedded path while retaining the full path in `item.path`/`id`/`title`; keyword and path stopwords removed from terms. `0.5905` / `0.3630` / hit@1 `0.2532` / ndcg `0.3998`. Multifile-60: recall@10 `0.8611`, MRR `0.8165`. Mechanical guard on stratified 150-case slice (`/tmp/mech150.jsonl`): `0.8377` vs H52 `0.8510`, delta `-0.0133`, below the `0.02` kill threshold — **PASS**. Key insight: the embedder caps at 500 chars / 512 tokens, so only the first sections reach the vector; every character counts.
- **H-66c** — manifest symbol-surface: **REJECTED**, uniformly worse (`0.5835` / `0.3506`).
- **H-64** — chunk-level, `intellij-h64-chunks.yml`: +96347 `symbol_chunk` points, +70.5% index. `0.5968` / `0.3674`; recall gain is noise. Arm 1 (`intellij-h64-arm1-wide-chunk-lane.yml`, chunk lane limit 340, multiplier 1.15) had the best ranking of the series: recall `0.5968`, MRR `0.3780`, hit@1 `0.2658`, ndcg `0.4103`, but recall was flat. Arm 2, per-kind path dedup (`vector_kind_path_dedup`, default OFF), regressed: dedup destroys file-vote aggregation. **Not promoted**: +70% index for +0.015 MRR and zero recall gain.

## Lessons to carry forward

1. `top_result_kind` / `first_relevant_kind` metrics are broken for multi-kind collections. `GraphFileRetrievalStrategy._representative_rank` always picks the `file_summary` point as the path representative, making the rate `1.0` by construction. This produced false “the kind never surfaces” kill verdicts for H-66c and base H-64. Fix by reporting the winning point’s kind before file-level collapse.
2. Per-path dedup inside a vector lane is harmful when file-vote aggregation is active.
3. Recall is not limited by document granularity. The remaining gap versus jbcontext (`0.5905` vs `0.685`) is candidate recall; the next lever is the candidate/lexical stage, not document representation.
4. All new behaviour is behind scanner/search flags defaulting OFF; only the new configs enable it.