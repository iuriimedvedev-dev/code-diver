# 2026-08 — Protocol of the month's work: retrieval quality, measurement rigour, and the answering core

Date: 2026-08-19. Covers all sessions Aug 1–19 on `code-diver`.
Sources: `.session/2026-08-0{4,5,13}*`, `.plans/2026-08-0{4,12,13}*`, commit history `8c8f294..3335091`.

## 1. TL;DR

The month had three arcs, in order:

1. **Instrument rigour first.** The judge was deconstructed (six criteria ≈ one axis), a silent
   data-loss bug was found, latency methodology was rebuilt around machine state, and a fresh
   247-case corpus replaced the 100-case one.
2. **Retrieval arms, all pre-registered.** H15–H36 progressively closed the retrieval side on
   protogen: reranking kept, context widened, corpus made lean, rerank depth and fusion knobs
   found to sit at their optima. External validation (IntelliJ, CodeSearchNet) then *refuted* the
   champion's generality: the graph that powers it is actively harmful on JVM repos.
3. **The answering core became the product.** `code-diver answer`/`ask` now run the same measured
   pipeline the evals use; the pi front-end was repaired; the CLI is the interface.

Published headline numbers at month end:

| axis | corpus | metric | value |
|---|---|---|---|
| answer | protogen 247 | `citation_expected_recall` (champion h29) | **0.8171** |
| search | IntelliJ 1000 | recall@10, best measured (H46) | **0.9018** |
| search | IntelliJ 1000 | MRR@10, best measured (H46) | **0.8200** |
| search | CSN 1000 | recall@10 (champion-postfix) | **0.9730** |
| search | IntelliJ 1000 | recall@200 (H48, pool ceiling) | **0.9665** |

The central question the user set ("why does the large repo work worse") is now located with
evidence: **on a 74 906-file repo the candidate pool is not the bottleneck (recall@200 = 0.9665);
the loss is in top-10 ordering.** Two fixes were measured to recover it: kill the graph (H38,
+5.6 recall) and preserve the base top-1 through the cross-encoder (H46, +0.07 MRR).

## 2. Timeline

### Aug 4 — judge deconstruction, latency surgery, H15/H16

- **Judge halo (E2/E3), Findings 1–8.** The six judge criteria have mean pairwise Spearman
  0.66–0.79 → effectively one axis; `judge_specificity` is a dead criterion (stdev ≈ 0.25–1.03);
  judge failures were scored as zero-quality (reversed a model ranking); `judge_overall` is mostly
  restating `context_bundle_complete` (ρ = 0.762). Fixes shipped: abstention as first-class output,
  judge-error exclusion, `judge_scored_count`, shared unjudgeable-row policy, per-criterion
  reporting. Tests 742 → 799.
- **Latency (Findings 14–16).** 59% of end-to-end latency was a tokenization pass over the whole
  catalog with a fresh empty cache on every call. Persistent profile cache: search 61.7 s → ~2–5 s,
  end-to-end 104 → ~51 s/case, byte-identical retrieval. Finding 15: the win amortises across
  cases (query-independent profiles). The run also exposed the index is not lean (100% of items
  carry `content`, 83% are `node_modules`).
- **H15 (context budget 4→10):** mechanism confirmed (`context_bundle_complete` 0.46→0.60,
  p=0.0001), primary `answer_grounded` null (Finding 9: it is blind to the *second* file), post-hoc
  `citation_expected_recall` +0.055 (labelled post-hoc). Finding 10: bundle-completeness is a good
  descriptor, a bad intervention target.
- **H16 arm C (rerank ablation): REFUTED.** Rerank off loses 0.145 recall, guardrail worsens.
  Finding 12: an observational within-run split was a collider, only the ablation could settle it.

### Aug 5 — corpus, data-loss, and the 44-finding investigation (H17–H32)

- A silent data-loss bug: a judged baseline was clobbered from 100 → 10 rows (filename collision);
  bounded damage, fixed `compare_arm_runs.py`.
- **H17 (embedding truncation): REFUTED.** The real +0.085/+0.120 recall gain of the lean rebuild
  was **vendor removal** (corpus statistics / BM25 IDF), not caps (Finding 17). Lean `ctrl`
  collection = new baseline: Pareto win (latency 104 → 52 s/case), primary +0.050 (CI includes zero).
- Findings 17–60 closed the retrieval side on protogen: rerank depth has an interior optimum ~34
  (19, 20, 51); the rerank-model override had never reached the eval path (35) — methodology change;
  machine state is a uniform latency factor → use stage shares (37); cross-encoder survives the
  guardrail and moves the primary for the first time (39); the pool (0.141), not the cut (0.054) or
  generation (0.035), is the loss budget (50); retrieval is NOT bit-deterministic, the reranker is
  (50a); fusion/weights axis closed (H34, 55); directory-cluster diversity refuted (H33, 57).
- **H32-A (cut 14): REFUTED on the primary at 247 cases** (+0.0162, CI covers zero); mechanism
  replicates, conversion is ~20% (60). Champion stays at cut 10, 0.8171, 45.2 s/case.
- New instrument: **247-case answer corpus** (byte-identical 100-case prefix, 327/327 expected
  paths indexed). Standing rule: an effect discovered on a corpus must survive cases added *after*
  discovery before promotion.

### Aug 12 — H36/H37: depth refuted, the champion does not transfer

- **H36 (pool depth 34→100 on protogen): REFUTED.** Pool recall rose as predicted (0.883→0.953)
  but cross-encoder conversion fell (91.5→82.3%); deeper pools *lose* recall at fixed cut. The
  binding constraint is cross-encoder ranking quality at fixed width, not candidate supply.
- **Finding 63:** `graph_weight` had never had a graph on any JVM repo — `CodeGraphBuilder`
  dispatched imports on `.py/.ts` suffixes only, so the IntelliJ/CSN adjacency was `{}` and the
  0.45 term scored zero on every candidate. Fixed: `_jvm_imports` + `_jvm_class_index` (1 157 273
  edges, 1 081 652 cross-file on IntelliJ), correctness-gated by byte-reproducing the protogen
  artifact.
- **Finding 64 (H37): the champion does not transfer.** IntelliJ 1000: 0.8397 vs protogen 0.9025 —
  worse on every axis (nDCG, MRR, hit@1 all down) at 1.56× latency. CSN: +0.01 recall for 4×
  latency, off the Pareto frontier. Conclusion: tuning overfit protogen's *shape*, not its
  difficulty.
- **Findings 65–69:** H38 (graph off) +0.067 recall on 150 cases — the graph *outranks* vector
  evidence (`_normalize` gives the top graph-only file the full weight); the reranker has a
  **512-token silent-failure ceiling** (22% of CSN cases never reranked, zero evidence) — fixed
  `-b/-ub 768` + visible warnings; four-arm campaign (Finding 67): **H38 (graph off + xenc) 0.8958
  (+5.6, p=7.3e-10), H43 (graph off, no xenc) 0.8716 with best nDCG 0.8110 / MRR 0.8020 at
  2.00 s/case, CSN champion-postfix 0.9730, H44 0.9650 at 85% faster**; the cross-encoder buys
  recall and *costs* head order (H43 vs H38: recall −0.024, nDCG +0.039). Finding 68: 36 GB of
  swap → latency and quality must never share an arm (corrected: swap attribution refuted by a
  controlled re-run). Finding 69: search-axis replay is deterministic (999/1000 byte-identical).

### Aug 13 — answering core extraction, CLI, dogfooding

- Phases 1–4 landed: `AnswerService`/`AnswerPipeline` extraction; **`code-diver answer`** (primary
  command, `--json`, grounded answer + file:line citations); `ask` now defaults to the core (pi
  behind `--agent`); shared `add_answer_arguments()`. Tasks #41–#43 closed.
- pi extension repaired: added the missing `code_diver_answer` tool, replaced `uv run` (GitHub
  re-resolution killed arms) with the venv entry point, pointed provider defaults at the generator
  that actually starts here (`:8012` / Qwen3.5-4B).
- Two defects found by dogfooding: **sibling venvs were indexed** (`.venv-vllm-metal-official`
  = 21 413 files, run headed to 33 792 against 811 real) — fixed `.venv*/**` + `is_dir` matcher
  (a `dir/**` pattern no longer matches a file that merely shares the name). Tests 1080 green,
  ruff clean.
- §4 self-test: 5/6 answer cases byte-identical vs HEAD. The 1 diff was embedding float noise
  reaching the model through the prompt — **H47**: `AnswerContextBuilder` prints raw
  `score={score:.6f}`; exact answer-axis replay is impossible while that holds (measured
  hypothesis, not a quiet fix).

### Aug 14 — H48 pool depth on IntelliJ (PASS) and the H45/H46 campaign

- **H48 (search.limit 10→200, H43's stack): PASS.** recall@200 = **0.9665** (pre-registered
  ≥0.95). Only 25/1000 cases have the answer nowhere in the pool. Decomposition of the recall@10
  shortfall: **74.4% ranking, 25.6% pool-absent.** First-relevant file is scattered (29% in 11–20,
  ~20% in each farther band) → no window tweak captures it; the ranker must be better, not deeper.
  Recording Finding 70 in the plan.
- H45/H46 campaign ran to completion (all four reports on disk):
  - **H45a (graph ON): VOID — defect.** 240/247 cases returned zero retrieved files; the graph-on
    path silently empties the seed. Configs are byte-identical to H45b except `graph_weight`.
    Needs diagnosis + re-run; the champion's protogen graph contribution (≈ +0.14 search recall) is
    therefore *unmeasured*, not confirmed.
  - **H45b (graph off + xenc): 0.7598** recall@10.
  - **H45c (graph off, no xenc): 0.7861** (+0.026 vs H45b, p=0.405 n.s.; nDCG +0.034, p=0.118).
    Directionally consistent with IntelliJ (xenc costs head order), not significant.
  - **H46 (preserve top-1) vs H38, IntelliJ 1000: WIN.** recall +0.006 (6 better / **0 worse**,
    p=0.031), **MRR +0.0704 (p=0.0001), nDCG +0.0593 (p<0.0001)**. Preserving the base top-1
    through the cross-encoder repairs exactly the head-ordering damage H43 identified. Promotion
    candidate on both axes.

### Aug 19 — H45a Fix, Live Re-run (Resolution), H46 Promotion, and H49 Pre-registration

- **H45a Defect Fix & Live Re-run Resolution**:
  - Root cause resolved in `GraphFileRetrievalStrategy` (path normalization discrepancies between vector hits and catalog entries, missing candidate preservation on empty graph propagation).
  - Multi-tier path matching, robust normalization (`os.path.normpath`), and base fallback implemented. Unit tests verified (16 passed in `test_graph_file_retrieval_strategy.py`).
  - **Live Re-run on Protogen 247**: 247/247 cases succeeded (0 failed, 0 degraded; VOID defect completely eliminated).
  - **H45a (Graph ON, XEnc ON) vs H45b (Graph OFF, XEnc ON) vs H45c (Graph OFF, XEnc OFF)**:
    - `recall@10`: **0.8246** (H45a) vs 0.7598 (H45b, **+6.48 pp**) vs 0.7861 (H45c, **+3.85 pp**).
    - `MRR@10`: **0.6492** (H45a) vs 0.5536 (H45b, **+9.56 pp**) vs 0.5861 (H45c, **+6.32 pp**).
    - `nDCG@10`: **0.6661** (H45a) vs 0.5802 (H45b, **+8.59 pp**) vs 0.6140 (H45c, **+5.21 pp**).
    - `Hit Rate@1`: **0.5344** (H45a) vs 0.4170 (H45b, **+11.74 pp**) vs 0.4615 (H45c, **+7.29 pp**).
    - `Bundle Complete Rate@10`: **0.7571** (H45a) vs 0.6883 (H45b, **+6.88 pp**) vs 0.7247 (H45c, **+3.24 pp**).
    - **Conclusion**: On Protogen, the graph contributes substantial positive retrieval signal (+6.48 pp recall, +9.56 pp MRR), resolving the unmeasured gap.
- **H46 Promotion into Production & Reference Configurations**:
  - Promoted `preserve_top_candidate: true` and `preserve_top_score_margin: 0.1` into base `code-diver.yml`, answering champion `protogen-h29-xenc-strict-cite.yml`, benchmark configs (`codesearchnet-h37-champion-xenc-1000.yml`, `intellij-h37-champion-xenc.yml`, `intellij-h38-graph-off.yml`, `intellij-h46-preserve-top.yml`), and H45 evaluation configs.
  - Test suite validated: 1098 passed, 3 skipped.
- **H49 Pre-registration (`.plans/2026-08-19_h49-top10-ranking-optimization.md`)**:
  - Targets the 74.4% ranking shortfall identified in H48 (`recall@200 = 0.9665` vs `recall@10 ≈ 0.9018`).
  - Three arms designed: (1) rerank depth sweep (20–50), (2) feature fusion / score blending between hybrid stage-1 and cross-encoder logits, (3) multi-tier top-k & margin preservation.

### Aug 25 — Finding 71: cold-start tokenization tax, and a fix

- Task #40 (dedicated latency measurement) led to a stage-by-stage profile of the full
  `graph_file_cross_encoder` chain on the IntelliJ-scale (149,614-item) catalog, isolating each
  layer's cost on a fresh process. Result did not match the original hypothesis (an O(catalog)
  cost scaling per query) — that was refuted directly: once caches are warm, the graph
  strategy's own lexical loop adds only ~0.04s over base hybrid search per query. The real cost
  is a one-time, **per-process, in-memory-only, ~209s cold-start tax** paid before the first
  search result, decomposed into two measured components:
  - `HybridRetrievalStrategy._load_lexical_index` — builds the BM25 inverted index and profiles
    every one of the 149,614 catalog items (title/path/content/metadata term tokenization):
    **140.4s**.
  - `GraphFileRetrievalStrategy._seed_scores`'s own separate lexical-candidates loop —
    re-tokenizes the *same* 149,614 items into its own private, unshared `_item_profiles`
    dict, even though `GraphFileRetrievalStrategy.base_strategy` *is* the `HybridRetrievalStrategy`
    instance that just profiled them: **68.0s of pure duplicate work**.
  - Sum (208.4s) matched the independently measured full-chain cold call (209.269s) almost
    exactly. Pure catalog *structure* load (`FileGraphCatalogStore`, disk-cached) is only 3.4s —
    the cost is entirely in per-item term tokenization, not structure loading.
  - **Why this was invisible across the whole H37–H49 campaign**: every eval report to date
    measures *batch* runs (1000 cases/process), where the ~209s cost amortizes to ~0.2s/case —
    negligible next to per-case quality metrics. In *interactive* usage (a fresh CLI process per
    `ask`/`search` invocation — the real dogfooding scenario behind task #46), every single query
    pays the full ~209s (~3.5 minutes) before any embedding/vector-search/answer work starts. This
    scales with catalog size: on protogen (1911 files, ~1/40th the catalog) the same tax would be
    roughly 5s — tolerable; at IntelliJ scale it is an experience-breaking cliff, and unlike
    H48/H49 (steady-state ranking quality) this is a cold-start scalability defect.
  - **Root cause**: `HybridRetrievalStrategy` already has a module-level, process-shared,
    artifact-keyed cache pattern (`_SHARED_LEXICAL_INDEXES` et al.) for exactly this reason — but
    `GraphFileRetrievalStrategy` never participated in it, keeping its own private
    `_item_profiles = {}` despite always wrapping a `HybridRetrievalStrategy` instance
    (`RetrievalStrategyFactory._graph_file_strategy` always constructs it this way).
  - **Fix applied** (`graph_file_retrieval_strategy.py`): when `base_strategy` is a
    `HybridRetrievalStrategy`, bind `_item_profiles` and the profiling lock *by reference* to the
    base strategy's own — safe because `HybridItemProfile`s are pure/immutable and the base
    strategy's dict is mutated in place (`.update(...)`, never reassigned), and because
    `_seed_scores` always calls `self.base_strategy.search(...)` (populating the shared dict)
    before building its own scorer. Falls back to a private dict when `base_strategy` isn't a
    `HybridRetrievalStrategy` (test fakes), so existing unit tests were unaffected (104/104 green
    in the retrieval-strategy subset; 1098 passed / 3 skipped full suite).
  - **Measured result**: cold-start full-chain call dropped **209.269s → 140.117s** (−69.15s,
    −33%), matching the eliminated duplicate pass almost exactly. Confirmed the two strategies
    now share the literal same dict object (149,614 profiles populated once, not twice).
  - **Remaining cost (140s, not attempted)**: the real one-time BM25/profile build itself. A
    disk-persistence fix (mirroring how `FileGraphCatalogStore` already persists catalog
    *structure*) could eliminate most of this too, bringing interactive cold-start down near the
    3.4s catalog-structure-load floor — a larger, separate follow-up meriting its own
    hypothesis/design, not attempted this session.
  - Directly answers the "why does it not scale on a large repo" thread and is the concrete,
    previously-undiagnosed mechanism behind task #46 (interactive profile should drop more than
    just the LLM rerank — cold-start tokenization is the larger cost at IntelliJ scale).

## 3. Methodology rules that now govern measurement

- An effect discovered on protogen must survive an external corpus before promotion (Finding 60).
- A mechanism inferred from a two-variable comparison is a hypothesis, not a cause (Findings 57/68).
- Latency and quality never share an arm; latency needs an idle machine, ~150 cases is enough;
  record machine state next to every latency number (Finding 37/68).
- A within-run split by a model's own behaviour is not an ablation (collider) (Finding 12).
- A weight is not evidence a mechanism runs — assert the artifact (Finding 63's standing caution).
- Correlational ranking metrics do not survive being optimised (Findings 5/10).
- A post-hoc metric is labelled post-hoc or it is not evidence (Finding 11).

## 4. State of the machine and measurement debt at month end

- **Servers:** all down (embedder :8001, generator :8012, reranker :8081, qdrant :6333) — the
  machine was returned to the user; nothing is running.
- **Git:** branch `h37-external-validation` @ `3335091` (H48 config committed); `main` is 4 ahead
  of origin, nothing pushed.
- **Tests:** 1080 passed / 3 skipped, ruff clean.
- **Open tasks:** #37 (large-repo default undecided — recall-first vs precision-first), #38/H46
  (resolved: re-run done, promoted to configs), #40 (latency, gated on idle machine), #45 (answer-axis
  external validation on IntelliJ 1000 + protogen re-baseline after refactor), #47 (H47 score-free prompt),
  **H45a resolved: bug fixed and live re-run completed (247/247 success, recall@10 = 0.8246)**.
- Immediate next campaign: execute H49 arms on IntelliJ 1000 / Protogen 247; then the answer-axis validation (#45).