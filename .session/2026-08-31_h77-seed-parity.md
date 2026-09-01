# 2026-08-31 — H-77 seed score parity promoted into the champion

## Decision

**PROMOTED.** `graph_file_search.seed_score_parity: true` is now set in
`configs/intellij/intellij-h66b-champion.yml`. The option itself defaults to `false`, so every
other config in the repo (including the archived `intellij-h46-preserve-top.yml`, untouched)
keeps bit-identical behaviour.

## Root cause it fixes

`GraphFileRetrievalStrategy._seed_scores` did not rerank the hybrid pool — it rebuilt each
candidate's score from two independent sources. A file that arrived through the vector lane but
was not in the lexical seed top-280 kept `lexical = path = symbol = 0.0` **structurally**, by
absence rather than by lack of a match, capping it at `vector_weight = 0.25` out of ~0.80.
Measured gold features at that stage: `vector=0.917 lexical=0 path=0 symbol=0 total=0.229`
against a distractor at `v=0.92 lex=0.69 path=0.50`. 14 of 79 WHERE cases died there.

The parity pass rescores exactly those vector-only candidates with the *same*
`HybridCandidateScorer` instance already built for the lexical seeds (same `HybridQuery`, same
`self.profiler`, same shared `_item_profiles` dict and lock), merged via the existing
`_update_max_score`. Fusion weights unchanged; the lexical seed path unchanged.

## Measurements (all runs strictly sequential, no reindex, collection `intellij_h66b_budget_qwen`)

### WHERE-79, same sitting (`datasets/intellij_eval_where_only.jsonl`)

| arm | recall@10 | MRR@10 | hit@1 | hit@10 | ndcg@10 | mean lat | p95 lat |
|---|---|---|---|---|---|---|---|
| champion floor | 0.5757 | 0.3708 | 20/79 | 51/79 | 0.4005 | 4898 ms | 5896 ms |
| H-77 | **0.6120** | 0.3679 | 18/79 | **54/79** | **0.4095** | 4402 ms | 4307 ms |

### 1065 gate, H-77 (`datasets/intellij_eval_1000.answer_sets.jsonl`), 2h04m warm

overall recall@10 **0.8353**, MRR@10 0.7189, hit@1 0.6319, hit@10 0.8629, ndcg@10 0.7337,
mean 3554 ms / p95 5743 ms. Buckets:

| bucket | n | recall@10 | MRR@10 | hit@1 | hit@10 |
|---|---|---|---|---|---|
| config | 329 | 0.8784 | 0.7491 | 0.6474 | 0.9301 |
| path | 328 | 0.8577 | 0.7664 | 0.7012 | 0.8628 |
| symbol | 329 | 0.8235 | 0.7256 | 0.6444 | 0.8389 |
| where | 79 | 0.6120 | 0.3679 | 0.2278 | 0.6835 |

Archived champion overall was ~0.8175, so H-77 is ~+1.8pp — but that is a **cross-sitting**
number and this box drifts ~2x day to day, so it is context, not evidence.

### Same-sitting comparator: mechanical guard slice (150 cases, 50 config / 50 path / 50 symbol)

A full champion 1065 run would have cost another ~2h and the budget did not allow it, so the
honest same-sitting comparison is the stratified guard slice, run on both configs back to back.

| metric | champion | H-77 | delta |
|---|---|---|---|
| recall@10 overall | 0.7977 | 0.8381 | **+0.0404** |
| MRR@10 | 0.7236 | 0.7472 | +0.0236 |
| hit@1 | 0.6400 | 0.6667 | +0.0267 |
| ndcg@10 | 0.7169 | 0.7435 | +0.0266 |
| recall@10 config | 0.7463 | 0.8143 | +0.0680 |
| recall@10 path | 0.8813 | 0.9013 | +0.0200 |
| recall@10 symbol | 0.7653 | 0.7987 | +0.0334 |
| mean latency | 4533 ms | 4218 ms | −315 ms |

## Decision rule

"Promote only if no mechanical bucket loses more than 0.01 recall@10 and overall recall@10 does
not drop more than 0.01." Every mechanical bucket **gained**; nothing regressed. Rule passes.

## Accepted regressions

- WHERE-79 hit@1 20 → 18 (0.2532 → 0.2278). Expected shape: parity gives real lexical/path mass
  to previously-suppressed vector candidates, so they legitimately compete near rank 1.
- WHERE-79 MRR@10 −0.0029 — flat, an order of magnitude smaller than the recall gain.
- Guard slice MRR/hit@1 both improved, so the hit@1 cost looks WHERE-specific, not systemic.

## Rejected arms (measured, kept as documented configs)

- `intellij-h78-ce-doc-window.yml` (CE `max_document_chars` 850 → 1600): best recall on record
  (0.6422, 56/79) but MRR collapses to 0.3224 and ndcg 0.3833 falls **below** the champion floor.
- `intellij-h79-preserve-top2.yml` / `intellij-h79b-preserve-top3.yml`: no-op — depth 3 is
  bit-identical to H-77, depth 2 marginally worse on MRR. The margin gate almost never fires at
  the depth-2/3 cut point, and the motivating cases are demoted from base ranks 7 and 9 anyway.

## Dataset hygiene (reported, NOT applied — no dataset row was changed)

- `where-editor-caret` lists a gold that does not exist on this revision
  (`.../editor/impl/EditorCaretMoveProcessor.kt`), capping the case at 3/4.
- `where-json-file-parsing`'s single gold `json/gen/com/intellij/json/JsonParser.java` sits under
  `**/gen/**`, which `indexing.exclude` drops, so it is not in the collection and the case is
  structurally unwinnable.
- Honesty correction (drop the stale gold, drop the unwinnable case, n=78) is **~+1.0pp recall@10**,
  not the ~2.5pp previously assumed, and it is uniform across arms — floor 0.5853, H-77 0.6220 —
  so it changes no verdict.

## Next steps

- If a full champion 1065 run becomes affordable, run it in one sitting with H-77 to replace the
  cross-sitting 0.8175 reference.
- Retry the CE document window at an intermediate value (1000-1200), or widen only for candidates
  the cross-encoder scored near zero, instead of a blanket doubling.
