# Handoff: code-diver ranking-quality research (2026-08-25 → 2026-08-26)

Purpose of this file: everything a new agent needs to pick up this work cold — mandate,
standing rules, what's done, what's in flight, what's next, and where all the evidence lives.
Nothing in here should need re-deriving; read `.session/2026-08-25_jbcontext-comparison-report.md`
for full technical detail on any claim below (it's the primary findings document, this file is
the orientation/protocol layer on top of it).

## 1. Mandate

User granted a 12h autonomous session (started 2026-08-25) with four asks, all now addressed:
1. Build a harder eval dataset requiring multiple files per answer.
2. Deep-investigate where code-diver's retrieval pipeline is weak and why.
3. Save the code-diver-vs-jbcontext comparison + deep analysis as a report.
4. Fix code-diver's shortcomings; find and integrate strong open eval datasets.

Work has since continued past the initial four asks into a second research round (user
explicitly asked for an Opus deep-research pass on the root cause, then asked to implement two
of the resulting quick-win hypotheses). Treat the mandate as **open-ended, continuing** unless
told otherwise — this is an ongoing research thread, not a closed ticket.

## 2. Standing protocol — hard rules, violate none of these

1. **Never run two evaluation/benchmark processes concurrently.** Not code-diver eval alongside
   jbcontext, not two code-diver eval variants, not an eval alongside an unrelated model
   benchmark that touches the same servers. Check `ps aux` before starting any run. This is a
   forceful, repeated standing instruction from the user (see memory
   `feedback_sequential-evals-only.md`) — concurrent runs measurably skew each other's
   latency/perf numbers and the user does not trust results produced that way.
2. **Full-scale datasets only for reported numbers.** Small pilot samples are fine for fast
   iteration (e.g. `datasets/intellij_eval_where_only.jsonl`, 79 cases, ~2-3min/run) but never
   report a "final" number from a sample when the full dataset is available.
3. **Subagents get no notification for their own background children.** This has cost real
   wall-clock time 3+ times this session (a subagent backgrounds a long eval, stops its turn,
   and waits for a "completion notification" that only the top-level session ever receives).
   Every prompt to a subagent that will run/wait on a live process must explicitly say: run it
   in the foreground (no `&`/`run_in_background`) so the tool call blocks naturally, or if
   backgrounded, poll synchronously in a loop inside one tool call. See memory
   `feedback_subagent-background-notification.md`.
4. **Never touch the champion config directly.** Champion is
   `configs/intellij/intellij-h46-preserve-top.yml`. Every experiment is a new config file
   (`intellij-hNN-description.yml`), ideally with new features gated behind an
   off-by-default config flag so the champion is provably unaffected. Only promote to champion
   with a clear, validated win and — per the last delegated task's instructions — ask before
   doing so rather than doing it unilaterally.
5. **Honest null results are a valid, valued outcome.** Two ranking-fix hypotheses (H-A, H-B,
   §8 of the comparison report) were implemented, tested, and reported as refuted with evidence
   rather than cherry-picked into a fake win. Keep doing this. Do not force a promotion because
   a metric moved slightly if another metric regressed or the effect is inside a bootstrap CI
   that spans zero.
6. **Verify agent claims before repeating them.** Every agent report in this session was
   spot-checked (re-reading the actual result JSON, checking `git status` on files claimed
   untouched, re-running pytest) before being relayed. Keep doing this — agents are honest here
   so far, but claims should still be checked, not just trusted.

## 3. What's done (completed, evidence on disk)

Full detail in `.session/2026-08-25_jbcontext-comparison-report.md` §1-10. Summary:

- **§1-5**: code-diver vs jbcontext headline on the 1065-case IntelliJ dataset — code-diver wins
  on 3 mechanical categories (symbol/config/path), jbcontext wins on the 79-case realistic
  "where" category (recall@10 0.685 vs 0.503). jbcontext's `--reranker BEST` flag is a confirmed
  no-op in this environment.
- **§6**: root-cause investigation of the "where" shortfall — **later corrected** by the Opus
  pass in §11 below, see that section for the current-best diagnosis.
- **§7**: new 60-case multi-file-answer dataset (`datasets/intellij_eval_multifile.jsonl`) —
  code-diver still wins every metric but the hit@1 lead vanishes into an exact tie (0.633=0.633)
  once answers need 2-4 files instead of 1.
- **§8**: H-A (family-size score dampening) and H-B (widen rerank window on uncertainty) both
  implemented as config-gated/off-by-default, both refuted on the where-only subset with
  evidence (H-A mathematically inert, H-B trades recall for hit@1/MRR + unconditional latency
  cost). Champion untouched, full test suite (1083 passed/3 skipped at that point) verified.
- **§9**: SWE-bench-Verified integration — fixed a real commit-collision path-overwrite bug and
  a corpus-easiness bias (was qrel-only, now the full 58,058-file corpus) in
  `src/code_diver/benchmarks/mteb_swebench_preparer.py`. First live run: recall@10 = 0.174
  (expected, untuned baseline) but surfaced a **serious unresolved perf bug**: 48.2s mean
  query latency, 9h43m total wall-clock for 621 queries. Not yet root-caused (task #60).
- **§11 (Opus deep-research pass, this is the current-best diagnosis, supersedes §6)**:
  corrected the root cause. It is NOT primarily same-directory sibling cannibalization (only
  19.5% of distractors share a directory) — it's repo-wide "name-echo distraction" (85.7% of
  distractors echo a query token) compounded by a much deeper problem: **the embedded document
  contains almost no natural-language prose at all**. `file_manifest` records spend 75.7% of
  their 500-char budget on path/package tokens, keeping only ~1.7 of ~18.8 symbols per file.
  Cross-encoder reranker verified live as saturated (1.3% dynamic range on real siblings), not
  broken — it has nothing semantic to discriminate with. `recall@200` = 0.924 vs `recall@10` =
  0.503 on the where bucket — this is 100% a ranking/representation problem, pool depth is fine.
  Produced 7 ranked hypotheses (H-1 through H-7) grounded in cited external research (Set-Encoder,
  SweRank, CoREB, "Do not copy and paste" on why query rewriting/HyDE measurably hurts this exact
  model). Query rewriting/HyDE and MMR/diversity reranking are explicitly ruled out by cited
  evidence — do not spend a run on either.
- **Feasibility check on H-1** (this session's newest finding): full-corpus LLM summarization to
  add differentiating prose is **NOT achievable in a 10-minute reindex** — measured (not
  estimated) on this machine (M3 Max, llama.cpp/Metal, real files, real model): need 125.6
  files/sec, best achieved 2.07 files/sec (16-way batched) → **~60x too slow**, ~10 hours for a
  full pass. Verdict: this must be a one-time/rare full pass plus **incremental,
  content-hash-keyed caching** thereafter (median 3 changed files/commit sampled from real
  IntelliJ history → trivially fast incremental updates). Also found a real, previously
  unknown bug as a side effect: 7,026 files (9.3% of the corpus) are test files that escape the
  current `**/test/**`/`**/tests/**` exclusion patterns (misses `testSrc/`, `testSources/`,
  `platform-tests/`) — folded into H-7.

## 4. In-flight work — NOT yet returned, check before starting anything else

**Task #63** (H-2/H-5 quick config wins) is `in_progress`, agent id `a40d1c3a396395cc1`,
launched this session, has not yet reported completion as of this handoff. It's implementing:
- **H-2**: raise `embedding.max_input_chars` from 500 (new config
  `configs/intellij/intellij-h51-max-input-chars.yml`, and a manifest-weight variant
  `intellij-h51b-manifest-weight-down.yml` already exist on disk from its work so far).
- **H-5**: fix the `query_prefix`/`document_prefix` template mismatch (Qwen3-Embedding model
  silently getting EmbeddingGemma-style default prefixes) — new config
  `configs/intellij/intellij-h52-query-prefix.yml` already exists on disk.

**When resuming**: check task #63's status first (`TaskGet` or `TaskList`). If still
`in_progress` with no result, either wait for its completion notification (if you're the same
session that launched it) or, if starting fresh, check whether those two config files already
have validation results recorded anywhere (search recent `.code-diver/reports/*h51*`,
`*h52*` — none existed as of this handoff's snapshot) before deciding whether to resume or
re-launch that work.

## 5. Open follow-on tasks, ranked

- **#60** (pending, arguably highest priority — blocks all further SWE-bench work): root-cause
  the 48s/query latency anomaly. Suspect BM25/lexical candidate scoring or graph containment not
  scaling to the SWE-bench index's 115,000 retrieval records (vs IntelliJ's smaller index).
- **#63** (in_progress, see §4): H-2/H-5 quick wins, awaiting agent completion.
- **#62** (pending, highest-impact but expensive): H-1, re-index with differentiating
  LLM-generated file-purpose prose. Now scoped with real throughput numbers (§3 above) — must be
  designed as a one-time/incremental job, not a per-index-run cost. Needs: (a) a prompt that
  asks the LLM to *differentiate* a file from its neighbors, not just describe it in isolation
  (cited SIGIR evidence: shared-context summaries measurably regress in-document discrimination
  by up to 53%); (b) content-hash-keyed caching so only changed files get re-summarized; (c)
  validation on the where-only subset first, then full 1065, tracking a hard-negative-intrusion
  metric (CoREB-style) alongside recall/ndcg as a guard against a flattering-but-fake win.
- **H-4** (route-conditional weights at the `graph_file_search` stage) — do only after H-1/H-2,
  it's a fusion-layer fix and the evidence says fusion isn't where the loss is (H50b: stripping
  everything but the dense channel only cost 0.084 recall, not significant).
- **H-6** (hard-negative LoRA fine-tune of the embedder) — best-measured technique in the cited
  literature but likely premature; do only after H-1, since fine-tuning an embedder to
  discriminate documents that are still 76% path string is fixing the wrong layer first.
- **H-7** (exclude test files properly) — trivial, fold into whichever re-index effort happens
  next (H-1 or H-2), don't spend a dedicated cycle on it alone.
- **#45, #46, #47, #30, #24, #23, #18, #17, #15** — older pending items from before this
  session's work, unrelated to the current research thread, still open, lower priority relative
  to the above unless the user redirects.

## 6. Key artifacts inventory

**Reports/analysis**: `.session/2026-08-25_jbcontext-comparison-report.md` (primary findings
doc, §1-11), this file (`.session/2026-08-26_handoff-protocol.md`).

**Datasets**: `datasets/intellij_eval_multifile.jsonl` (60 cases, multi-file answers),
`datasets/intellij_eval_where_only.jsonl` (79 cases, fast-iteration subset of the realistic
"where" category).

**Experiment configs** (none promoted to champion, all reversible): `intellij-h49-family-penalty.yml`,
`intellij-h49-widen-gate.yml` (refuted), `intellij-h50-vector-lean.yml`, `intellij-h50b-dense-only.yml`
(diagnostic, both null/informative), `intellij-h51-max-input-chars.yml`, `intellij-h51b-manifest-weight-down.yml`,
`intellij-h52-query-prefix.yml` (H-2/H-5, validation pending per §4). Benchmark config:
`configs/benchmarks/swebench-verified-mteb-500.yml`.

**Result JSON on disk**: `.code-diver/reports/codediver-multifile.json`,
`.code-diver/reports/jbcontext-multifile.json`, `.code-diver/reports/swebench-verified-500-first-run.json`,
plus the older 1065-case reports referenced in the comparison report §2. H-50a/b raw output at
`/tmp/h50/*.json` (not committed, `/tmp` — copy to `.code-diver/reports/` if they need to survive
a machine restart).

**Source changes so far** (all uncommitted — `git status` shows these modified, nothing has been
committed this session, confirm with the user before committing):
`src/code_diver/strategies/hybrid_retrieval_strategy.py` (H-A), 
`src/code_diver/strategies/cross_encoder_rerank_retrieval_strategy.py` (H-B),
`src/code_diver/config/{hybrid_search_config,cross_encoder_rerank_config}.py` + `config_loader.py`
+ `settings/defaults.py` (config plumbing for H-A/H-B), `src/code_diver/strategies/graph_file_retrieval_strategy.py`
(read/touched during the Opus investigation — verify what changed there before assuming it's a
no-op diagnostic edit), `src/code_diver/benchmarks/{mteb_swebench_preparer.py new,
benchmark_preparer_utils.py new, benchmark_asset_service.py, benchmark_preparation.py,
benchmark_profile_registry.py, mteb_codesearchnet_preparer.py}` (SWE-bench integration + fix),
`scripts/compare_jbcontext.py` (new, jbcontext comparison harness), plus corresponding test files.
Full test suite last verified green (1083 passed, 3 skipped) before the Opus/throughput/H-2-H-5
rounds — **re-run `pytest tests/unit -q` before trusting that number still holds**, since more
source files have changed since that check.

**Memory** (persists across sessions, at
`~/.claude/projects/-Users-iurii-medvedev-Work-code-diver/memory/`): `project_jbcontext-comparison.md`
(full comparison findings + root cause + null results), `project_swebench-latency-anomaly.md`
(task #60 context), `feedback_sequential-evals-only.md` and
`feedback_subagent-background-notification.md` (both protocol rules, §2 above), `MEMORY.md`
(index of all of the above, always loaded into context automatically).

## 7. Recommended immediate next step

Wait for or check on task #63's agent (`a40d1c3a396395cc1`). Once it reports, verify its numbers
independently (re-read the result JSON, don't just trust the summary), update the comparison
report §8/§9 area or add a new §12 with the H-2/H-5 outcome, and update task #63 to `completed`.
Then decide with the user whether to proceed to #60 (latency bug, blocks SWE-bench) or #62 (H-1
implementation, the highest-impact but most expensive item) next.
