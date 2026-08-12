# H16 — retrieval depth: is the answer beyond rank 10?

Status: **prepared, not run.** Blocked on H15 finishing (GPU contention).
Prepared while H15 (`CONTEXT_FILES=10`) runs.

## Why this is the next hypothesis

H15 tests whether widening the *context window* recovers the gap between
`candidate_bundle_complete` (0.620) and `context_bundle_complete` (0.460).
By construction it cannot exceed 0.620 — that is the ceiling of the candidate
list. H16 attacks the ceiling itself.

Established invariants across all 100 cases of
`.code-diver/reports/strict-judge/h14-qwen35-4b-answer-strict-qwen35-9b.json`:

- `len(retrieved_files) == 10` for every case (min = max = 10)
- `query_plan.final_rerank.candidate_count == 34` for every case

Two hard caps, both invariant, both currently unexamined.

## Evidence 1 — the recall curve has not converged at 10

Rank of each expected path inside `retrieved_files` (163 expected paths over
100 cases):

| recall@k | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| | .344 | .442 | .534 | .577 | .607 | .626 | .663 | .687 | .693 | .699 |

49 of 163 expected paths (30%) are outside the top 10 entirely. The curve is
flattening but still gaining ~0.01/rank at k=10 — it is truncated, not
converged. Deltas at 7→8 (+.024) and 6→7 (+.037) are larger than at 3→4
(+.043 vs .030 at 4→5), so the tail is lumpy rather than exhausted.

## Evidence 2 — the loss is concentrated in the second expected path

61 of 100 cases have 2 expected paths. Of those:

| outcome | n |
|---|---|
| both paths in top-10 | 33 |
| exactly one in top-10 | **19** |
| neither | 9 |

Ranks of the harder (second-found) path when both are found:
`1,1,1,1,1,1,1,2,2,2,2,2,2,2,3,3,3,4,4,4,5,6,6,6,6,6,6,7,7,7,7,8,9`

The second path is spread almost uniformly over ranks 1–9 with no decay at the
top end — six cases at rank 6, four at rank 7. A distribution that is still
flat at the truncation boundary is the signature of a cut that is too shallow.
Those **19 half-found cases are the target population**: each one converts a
0 to a 1 on `context_bundle_complete` if its missing path sits in ranks 11–34.

Upper bound if all 19 converted: bundle_complete 0.460 → 0.650. Realistic
target: the 11–34 band is 24 slots against 10, so recovering even a third of
them is +0.06.

## Evidence 3 — the LLM reranker is not earning its cost

`len(final_rerank.selected_indices)` distribution over 100 cases:

| selected | 1 | 5 | 6 | 9 | 10 | 34 |
|---|---|---|---|---|---|---|
| cases | **40** | 3 | 2 | 1 | 53 | 1 |

In 40 cases the reranker returns a **single** candidate out of 34; the other 9
of the 10 `retrieved_files` are deterministic backfill. Outcomes by group:

| group | n | ctx_bundle | cand_bundle | cand_recall | grounded |
|---|---|---|---|---|---|
| selected = 1 (9/10 backfilled) | 40 | **0.450** | **0.650** | 0.713 | **0.750** |
| selected = 10 (fully reranked) | 53 | 0.434 | 0.585 | 0.708 | 0.698 |
| other | 7 | 0.714 | 0.714 | 0.786 | 0.714 |

The mostly-backfilled group scores **higher** on every metric than the fully
reranked group. The LLM rerank costs ~13.5 s/case (`final_rerank.duration_ms`)
and, on this evidence, buys nothing. It is not a no-op either — 0 of the 53
sel=10 rows reproduced the deterministic order `[0..9]`, so it actively
reorders; it just does not reorder better.

Caveat: this is observational, not randomised. Cases where the reranker
returns 1 candidate may be systematically easier. The confound is testable and
arm C below tests it directly.

## Implementation map (verified against source)

Where the two invariants come from, in
`configs/context-awareness/protogen-h14-qwen35-4b-text-graph.yml`:

| cap | value | set by | CLI override |
|---|---|---|---|
| final `retrieved_files` (`AnswerEvaluator.limit`) | 10 | `evaluation.limit` | **`--limit N` exists** (`cli.py:675`), H14 script never passes it |
| rerank input pool / merge cap | 34 | `llm_rerank.candidate_limit` | none — YAML only |
| rerank output requested from the LLM | 10 | `llm_rerank.rerank_limit` | none — YAML only |
| per-probe-query pool | 34 | derived: `query_limit = max(limit, candidate_limit)` (`answer_evaluator.py:329`) | — |

The two caps are **coupled**: `query_limit = max(self.limit, candidate_limit)`.
So `--limit 20` alone lifts the final cut to 20 (34 ≥ 20 leaves headroom);
going past 34 additionally requires editing `llm_rerank.candidate_limit`.

Backfill confirmed in `AnswerCandidateReranker._reranked`
(`answer_candidate_reranker.py:62-70`): unselected candidates are appended
after the LLM's picks in deterministic merged-score order, then sliced to
`limit`. Nothing is dropped — which is why `recall@10` is largely a
measurement of the *deterministic* ranking, not of the reranker.

Cost structure: exactly **3 generation calls per case** (plan, rerank, answer)
regardless of depth. Raising `--limit`, `candidate_limit`, `--query-count`,
`graph_file_search.*` or `hybrid_search.*` adds **zero** LLM calls. Only
`candidate_limit` has a token cost (the rerank prompt already runs 15 400 input
tokens at 34 candidates with `max_preview_chars: 850` each). Depth is cheap.

## Arms

All on the same 100 cases, same model (`mlx-community/Qwen3.5-4B-OptiQ-4bit`),
holding the H15-winning `--context-files` / `--context-lines` fixed.

| arm | change | question |
|---|---|---|
| **B — deeper cut** | `--limit 20`, `llm_rerank.candidate_limit: 60`, plus pool instrumentation | Does depth move `context_bundle_complete` / `answer_grounded`, and where do the misses actually sit? |
| **C — rerank ablation** | drop `--agentic-query-rerank`, everything else fixed | Is the 13.5 s/case LLM rerank worth keeping? |
| **D — wider probing** | `--query-count 8`, depth unchanged | Free recall: more probe queries cost no extra LLM calls, only parallel vector work |

**The originally planned cheap gating arm A is dropped.** The retrieval-only
entry point does exist — `code-diver evaluate --dataset X --json`
(`cli.py:2048`) runs `EvaluationService.evaluate()` and reports
`file_recall@k` / `file_hit_rate@k` / `ndcg@k` with no answer generation. But
it calls `retrieval_strategy.search(case.query, limit)` with **one query per
case**: no query planner, no 4-probe fan-out, no merge. That is not the H14
candidate pool, so its recall@k curve would not gate a decision about H14's
cut depth. Two caveats compound it: the H14 config sets
`search.strategy: graph_file_rerank`, so `evaluate` would still make LLM
rerank calls unless pointed at a `graph_file` variant; and
`DatasetLoader._case_from_row` requires a `query` key, while
`protogen_answer_cases_100.jsonl` uses `question` (a key rename is needed —
`expected` is already a genuine JSON array, correcting an earlier note that
called it a Python-repr string).

Cheap-but-wrong beats nothing only when the proxy is faithful. Here it isn't.

## Instrumentation prerequisite — LANDED

`query_plan.final_rerank.candidate_pool` now persists the full merged
pre-rerank pool (`rank` 1-based, `path`, `id`, `score`) on **both** the
rerank-enabled and rerank-disabled paths
(`answer_evaluator.py:339-344`, `_build_candidate_pool` /
`_disabled_rerank_payload`). Ranks share the 1-based convention of
`selected_candidates[i].index`, so the two join directly. Suite 799 → 800.

**Config constraint this imposes:** the pool is `merged[:candidate_limit]`,
kept consistent with `candidate_count`. Since `merged` is capped at
`query_limit = max(limit, candidate_limit)`, setting `limit > candidate_limit`
would let backfill put files into `retrieved_files` that are absent from the
persisted pool. Keep **`candidate_limit >= limit`** in every arm. Arm B
(`limit 20`, `candidate_limit 60`) satisfies this.

## Rationale (superseded by the above, kept for the record)

Persist the full merged pre-rerank pool — paths plus base scores — in
`query_plan`, alongside the existing `candidate_count`. Today
`final_rerank.selected_candidates` holds only the LLM's picks (one single
candidate in 40 of 100 cases), so ranks 11–34 are unrecoverable and no depth
question can be answered offline.

This is ~34 short strings per case. With it, arm B's single run answers both
questions at once: whether depth 20 helps *and*, from the persisted 60-pool,
exactly where the still-missing paths rank — which is the gate for whether any
further depth increase is worth running. Without it we would be back to one
blind 3-hour run per depth value. Every depth question after this one becomes
a free offline simulation.

This is the same move that made the context-budget sweep cheap: pay once for
the data that lets you simulate, then stop buying GPU time to answer questions
arithmetic can settle.

## Pre-committed evaluation criteria

Decided before seeing results, to avoid post-hoc metric shopping:

- Rank arms on **`context_bundle_complete`** and **`answer_grounded`**, with
  95% CIs. Both are deterministic.
- Report `citation_fabricated_rate` as a guardrail — deeper context must not
  increase fabrication.
- **Do not rank on `judge_overall`.** Finding 5 showed it is largely a proxy
  for `context_bundle_complete` (ρ = 0.762) and saturates at 4.99/5 whenever
  the bundle is complete, and the existing baselines were judged by the old
  aggregation. Report it, do not decide on it.
- Report mean s/case for every arm. Arm C's whole case is latency.
- Secondary, for arm A only: recall@k curve and the count of the 19 half-found
  cases whose missing path appears in ranks 11–34.

## Risks

- Deeper retrieval feeds more files to the answerer, which may *lower*
  grounding by dilution — the opposite of H15's mechanism. Guard with
  `citation_fabricated_rate`.
- Arms B and C both change context size relative to the H15 winner. Hold the
  H15-winning `--context-files` / `--context-lines` fixed across B and C so
  depth is the only moving variable.
- GPU is single-tenant. Arms run sequentially; A first because it is cheapest
  and gates the rest.
