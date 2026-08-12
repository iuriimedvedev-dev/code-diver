# 2026-08-04 — latency: the search stage was re-tokenizing the whole catalog

Goal reframed by user: find the Pareto optimum between latency and quality of
search + explanation. First move: remove waste before trading quality for speed.

## Measured Pareto points before this work (100 cases each)

| config | `citation_expected_recall` | s/case |
|---|---|---|
| cf4, rerank on (H14 baseline) | 0.610 | 104.0 |
| cf10, rerank on (H15) | 0.665 | 112.9 |
| cf4, rerank off (H16 arm C) | 0.465 | 87.7 |

Marginal rates +0.0062/s (H15) and +0.0089/s (arm C, reading backwards). No
cheap win among the quality levers — every one of them buys quality with time.

## Finding 14 — 59% of end-to-end latency was a cache that was never passed

Search = 61.7 s of the 104.0 s per case, and none of it is LLM time.

Localised to `GraphFileRetrievalStrategy._seed_scores`
(`graph_file_retrieval_strategy.py:98-117`): a linear pass over every catalog
item (47,085 of them) re-tokenizing title/path/content/metadata, with
`HybridCandidateScorer` constructed on line 99 holding a **fresh empty profiles
cache on every call**. Measured ~17.8 s per pass. `answer_evaluator` fires 4
probe queries concurrently, but the work is `re`-bound so the GIL serialises
them: 4 x ~18 s ≈ the observed 61.7 s. It was never a single 60 s computation.

Not an architectural tradeoff — an inconsistency. The sibling
`HybridRetrievalStrategy` already keeps a persistent `_item_profiles` dict + lock
and passes it in, and `HybridCandidateScorer._profile()` already supported an
external cache under a lock. `GraphFileRetrievalStrategy` reimplemented the
scan and just never supplied one.

Refuted along the way: per-kind embedding multiplication (it is 1 embed + 5
Qdrant per probe query, no fan-out); large-JSON-parsed-per-call (0.27 s, once
per process, already cached in `_SHARED_GRAPHS` / `_SHARED_LEXICAL_INDEXES`).

## Fixes landed (suite 817 -> 822)

1. **Persistent profile cache** in `GraphFileRetrievalStrategy`:
   `self._item_profiles: dict[str, HybridItemProfile]` + `RLock`, passed as
   `HybridCandidateScorer(..., profile_lock=self._cache_lock)`. Same idiom as
   `HybridRetrievalStrategy`. The lock is load-bearing: 4 probe queries share
   one strategy instance.
2. **Skip `_graph_scores` when `graph_weight <= 0`**
   (`hybrid_retrieval_strategy.py:122`) — the config in use sets `0.0`.

Acceptance criterion was byte-identical retrieval output; a speedup that also
perturbs ranking is worthless mid-series because it confounds every arm.

**Gap in my own spec, caught by the implementer.** I asked only whether graph
scores leak through RRF (they do not — `_add_rrf` returns before touching
`item_ids` at `weight <= 0`). The second path I failed to name:
`graph_scores.items()` can *introduce new candidates* via
`scores.setdefault(item_id, ...)` — graph neighbours absent from both vector and
lexical results. At zero weight they contribute nothing, but they exist, and
with a pool smaller than `limit` they would pad the tail. Unreachable in
practice because `vector_limit = max(limit, candidate_limit)` with
`candidate_limit` = 280. Now covered by a test using a graph *with* an edge at
`graph_weight=0.0`, asserting identity with an edgeless graph.

## Finding 15 — the profile is query-independent, so the win amortises

Benchmark on the real catalog, CPU only, no embeddings/Qdrant/GPU:

| pass | query | wall | RSS after | cache |
|---|---|---|---|---|
| 1 (cold) | "where are prompt templates defined" | 17.784 s | 1038.1 MB | 47,085 |
| 2 (warm, same query) | same | **0.110 s** | 1038.1 MB | 47,085 |
| 3 (warm, **different** query) | "how does the retry logic handle rate limits" | **0.121 s** | 1038.1 MB | 47,085 |

RSS after catalog load alone: 374.0 MB.

Pass 3 is the important row. `HybridItemProfiler.profile()` tokenizes the
*item*, not the query, so a different query still hits the cache — 147x. The
win is not an artifact of query repetition.

I had underestimated this. The profiler's "45-60% of 61.7 s" assumed reuse
*within* a case. But the cache lives on a strategy instance reused across cases,
so the ~17.8 s is paid **once per process**: 0.18 s/case amortised over 100
cases, then ~0.5 s of scoring per case (4 x 0.12 s). Projected: search 61.7 s ->
~2-5 s (embedding + Qdrant + scoring), end-to-end 104 s -> ~45-50 s at
unchanged quality. Needs an end-to-end confirmation run.

## Memory: I raised this as a risk; it is not one

Cache costs 664 MB (1038.1 - 374.0), ~14 KB/item. Concern was unified-memory
contention with MLX models. Answer: 64 GB box with 16.8 GB of inactive
(reclaimable) pages. 664 MB is noise. Risk retired.

An LRU cap would be the wrong mitigation regardless, and for a specific reason:
`_seed_scores` iterates the *entire* catalog on every call, so any cap below
47,085 guarantees full eviction-and-retokenize every call — strictly worse than
no cache. If total memory ever needs bounding it belongs at the level of how
many strategy instances / catalogs are live, not inside this dict.

## Not done — deliberately

Third profiler suggestion: replace the linear scan with the existing inverted
index (`hybrid_lexical_index.py:32-36`, est. +10-15%). Profiler labelled it
free; it is not. Today every item is scored; via the inverted index, items with
no term match are never enumerated. If path/symbol scoring gives them nonzero
weight the candidate set changes. Separate step, separate equivalence proof.
Its value also drops sharply now — the scan it would replace costs 0.12 s.

## The architectural point this exposes (user's, and the numbers agree)

Design intent is a **lean file-level metadata index** — path, symbols, role,
short description — so that expensive detail work happens later on a small set
of chosen files. Two ways the current artifact violates that:

- **100% of the 47,085 items carry `content`**, ~61.4M chars. The index by
  files contains the code itself. That is what the 17.8 s tokenizes and the
  664 MB stores.
- **83% of items are `node_modules`** (40,082 of 48,284 points; 3,529 source
  files against 22,578 paths).

At ~3,500 lean items the cold pass would be ~1-2 s and the cache ~50 MB, and
none of this would have been worth an engineering step. The cache treats a
symptom. It is still the right first move — free, quality-neutral, and its
benefit survives any later catalog slimming.

Open question before touching exclude patterns: `codebase_scanner.py:261`
(`_matches_excluded_directory`, walk-time) **does** catch nested
`templates/frontend/node_modules/...`, while `_should_skip_file` at `:255`
(root-anchored `_matches_any`) does not. Verified both behaviours directly. So
current code would likely exclude vendor correctly and the collection is simply
**stale**. Determine how `code_diver_h14_gemma26_text_graph` was built before
"fixing" anything — a rebuild changes the corpus and breaks comparability with
all four H14 runs already recorded.

Note also: `graph_expansion_profile_factory.py` `_workflow` / `_path_symbol`
force `depth = max(depth, 2)` / `max(depth, 1)`, silently overriding
`hybrid_search.graph_depth: 0`. Harmless only while `graph_weight: 0.0`.

## Finding 16 — confirmed end-to-end, and the warmup step is visible

Run: `CASES=10 CONTEXT_FILES=4 CONTEXT_LINES=160 ./scripts/run_h14_model.sh
qwen35-4b qwen35-9b` -> `protogen-h14-qwen35-4b-text-graph-10.json`, 0 errors.

Decomposition per case: `duration_ms` total, `query_plan.duration_ms` (planning
LLM), `query_plan.final_rerank.duration_ms` (rerank LLM), residual = search +
answer generation. Residual is the only part this change touches.

| | new (10) | baseline, **same 10 case_ids** | baseline (all 100) |
|---|---|---|---|
| total | **55.0** | 113.3 | 104.0 |
| plan (LLM) | 8.8 | 8.2 | 8.0 |
| rerank (LLM) | 16.5 | 14.7 | 14.9 |
| residual (search+answer) | **29.6** | 90.5 | 81.2 |

Per-case residual, in execution order:
`74.9, 22.1, 18.4, 23.6, 27.7, 32.9, 20.6, 13.7, 40.6, 21.8`

**The step is exactly where Finding 15 predicted.** Case 1 pays 74.9 s; cases
2-10 average 24.6 s. This is the load-bearing observation — it proves the cache
survives *between cases*, not just between the 4 probe queries of one case. Had
the residual been flat, the strategy instance would not be long-lived and the
amortisation claim would have been wrong.

Steady state (cases 2-10): total 50.3 s/case, residual 24.6 s.
Projected at 100 cases: warmup amortises to ~0.5 s/case -> **~51 s/case vs
104.0 baseline, roughly half.**

Two honest qualifications:

- **Warmup cost 50.3 s, not the 17.8 s the microbenchmark measured.** The
  benchmark was single-threaded. Here 4 probe queries start cold simultaneously
  and contend on `_cache_lock`, so the first case pays more than one cold pass.
  Unexplained precisely; it is a one-time cost so it does not change the
  decision, but I should not present 17.8 s as the warmup number.
- **Plan and rerank both drifted *up* slightly** (+0.6 s, +1.8 s vs matched
  baseline). Those are LLM stages this change does not touch — run-to-run
  variance. Worth stating so the win is not overstated: the gain is entirely in
  the residual, and a little of it is given back elsewhere.

## What this run does NOT show: equivalence

`retrieved_files` matched the baseline exactly in only 4/10 cases (5/10 as
sets). That is **expected and not evidence of a regression**: the query planner
is an LLM, so probe queries differ between runs and identical retrieval is
impossible by construction. Equivalence is carried by the unit tests, not by
this run.

For the same reason the quality metrics here are uninformative — n=10, CI width
~±0.3, and they move in both directions (`answer_grounded` 0.700 vs 0.500,
`citation_expected_recall` 0.450 vs 0.500, `candidate_file_recall` identical at
0.600). **Do not read these as a quality result in either direction.**

## Revised Pareto table (latency projected at 100 cases)

| config | `citation_expected_recall` | s/case before | s/case after |
|---|---|---|---|
| cf4, rerank on | 0.610 | 104.0 | ~51 |
| cf10, rerank on | 0.665 | 112.9 | ~60 |
| cf4, rerank off | 0.465 | 87.7 | ~35 |

The shape of the decision changes. Rerank now costs ~16 s of a ~51 s budget
(31%, was 13%) for +0.145 recall — still clearly worth it, but it is now the
single largest remaining line item, ahead of answer generation. H15's context
widening costs +8.5 s for +0.055; against a 51 s base that is a much easier
call than against 104 s.

## Next

1. Re-measure the 100-case baseline at the new latency floor before running
   further arms, so every arm is compared against a current number rather than
   against 104.0 s.
2. `scripts/run_h16_arm.sh` output names do not encode the context budget
   (`protogen-h16-armc-qwen35-4b-100.json`), so re-running an arm at another
   budget silently overwrites. `run_h14_model.sh` does add a suffix. Fix before
   extending the series — silent data loss.
3. Arm B (depth 10->20) and arm D (`--query-count 8`) remain staged, awaiting a
   go-ahead. Both got cheaper in wall-clock terms.
