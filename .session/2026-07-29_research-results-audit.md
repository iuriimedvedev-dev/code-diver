# Research Results Audit — What Actually Wins, and What to Test Next

Date: 2026-07-29. All numbers re-derived from raw JSON in `.code-diver/reports/`,
not copied from prior markdown summaries. Where a prior doc disagrees, the raw
report is treated as authoritative and the disagreement is noted.

---

## 1. Best measured setups

### Public retrieval benchmark — CodeSearchNet/MTEB Python positive slice, 1000 cases

| Setup | FH@1 | FH@10 | nDCG@10 | mean ms | API $/1k | Report |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| H7 + Gemini Lite rerank (always) | **0.911** | **0.989** | **0.956** | 3488 | ~2.93 | `h8-train1k-gemini-lite-rerank-1000.json` |
| H9 body evidence (bounded) | 0.860 | 0.986 | 0.930 | 1601 | 0 | `h9-body-evidence-bounded-...-1000.json` |
| H7.1 API manifest | 0.858 | 0.987 | 0.930 | 1610 | 0 | `h8-train1k-h7-api-manifest-...-1000.json` |
| H6 deterministic | 0.856 | 0.987 | 0.929 | 3146 | 0 | `h8-train1k-h6-deterministic-1000.json` |
| H7.2 query expansion | 0.857 | 0.987 | 0.928 | **780** | 0 | `h8-train1k-h7-query-expansion-...-1000.json` |

Two readings that the existing docs do not state:

- **The four deterministic variants are one result, not four.** FH@1 spans
  0.853–0.860 and nDCG spans 0.928–0.930. That is inside the confidence interval.
  H7.1, H7.2 and H9 are null results *on quality*.
- **H7.2's real win is latency, not quality.** 780 ms vs 1601–3146 ms at equal
  quality — a 2–4x speedup. `docs/h7-adaptive-gated-rerank-2026-06-08.md` calls
  H7.2 "not a universal quality win", which is correct but files the wrong verdict:
  it is the cheapest way to reach the same quality and should be the default.
- LLM rerank is the only thing that moves FH@1 (+5.4pp). It buys 42% of the
  available `rerank_headroom@10` (0.130 → 0.078).

### Multi-language generalization (H6 + EmbeddingGemma-300M, 100 cases each)

| Language | FH@1 | FH@10 | nDCG@10 | coverage_gap@10 |
| --- | ---: | ---: | ---: | ---: |
| Go | 0.960 | 0.990 | 0.978 | — |
| Java | 0.910 | 1.000 | 0.963 | — |
| Ruby | 0.920 | 0.990 | 0.959 | — |
| Python (1000) | 0.857 | 0.987 | 0.928 | 0.013 |
| JavaScript | 0.850 | 0.960 | 0.911 | — |
| **PHP** | **0.730** | **0.870** | **0.806** | **0.130** |

Python is not the best language; Go/Java/Ruby all beat it. PHP is a 12-point
outlier and nothing followed up on it.

### Repo answer evaluation — protogen answer set, 100 cases

| Candidate | file_hit | ctx_file_hit | citation valid | ★Sum/24 | model calls | total tokens | errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **H12B + Gemini FL** | **0.89** | **0.89** | 0.987 | 17.73 | **100** | **1.40M** | 0 |
| H12A + Gemini FL | 0.86 | 0.86 | 0.957 | 16.55 | 100 | 1.44M | 0 |
| H14 + Gemma26 | 0.84 | 0.82 | **0.996** | **22.94** | 300 | 3.89M | 0 |
| H13 + Gemma26 | 0.82 | 0.79 | 0.940 | 21.83 | ~296 | — | 4 |
| H14 + Qwen9B | 0.64 | 0.62 | 0.882 | ~18.5 | 300 | — | 10 |
| H14 + Qwen4B | 0.51 | 0.48 | 0.856 | 19.13 | 300 | — | 11 |

**The best retrieval setup on this benchmark is H12B**, and it wins while using
one third of the model calls. H14's extra 200 calls (100 query-planning +
100 rerank, 2.49M extra tokens) produced *worse* retrieval.

---

## 2. Why the ★Sum leaderboard must not be used for ranking

### 2.1 Five variables change at once between H12B and H14

Recovered from the `settings` block of each report:

| Variable | H12B | H14 |
| --- | --- | --- |
| `agentic_queries` | False | True |
| `query_count` | 1 | 4 |
| `agentic_query_rerank` | False | True |
| answer/rerank/planner model | `gemini-3.1-flash-lite` | `gemma-4-26B-A4B-it-qat` |
| `doc_chunk` index lane | off | on |

No run isolates any one of these. `.session/2026-06-10_h14-qwen4b-report.md`
concedes the answer-model part; the other four are unacknowledged.

Worse, in H13/H14 **one model does three jobs** — query planning
(`mode: llm_multi_query`), reranking 34 candidates, and writing the answer.
So swapping the "answer model" also swaps the query planner and the reranker.
`H14+Qwen4B`'s `file_hit` 0.51 is not an answer-quality result at all: Qwen4B's
reranking collapses retrieval. Its actual defects are 11 empty generations and
6 failed query plans.

### 2.2 The strict judge tracks citation formatting, not correctness

| Candidate | JO | line-refs/answer | % answers w/ line-ref | bullets | r(len,JO) | r(file_hit,JO) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H12A + Gemini FL | 3.44 | 0.75 | 27% | 1.3 | 0.04 | 0.49 |
| H12B + Gemini FL | 3.73 | 0.85 | 32% | 1.1 | 0.15 | 0.36 |
| H14 + Qwen4B | 4.42 | 2.35 | 47% | 6.0 | 0.29 | 0.51 |
| H14 + Qwen9B | 4.53 | 2.60 | 57% | 8.5 | −0.01 | 0.37 |
| H13 + Gemma26 | 4.69 | 2.08 | 60% | 5.1 | 0.08 | 0.44 |
| H14 + Gemma26 | **4.75** | 2.12 | 64% | 4.8 | 0.14 | 0.58 |

- Judge score orders almost perfectly with **citation format density**, not with
  retrieval success. Both families use the same judge prompt
  (`prompts/code-answer-judge-strict.md`), so this is model output style.
- It is **not** length bias: `r(len, JO)` is 0.04–0.29.
- The judge only weakly tracks whether the right file was even found:
  `r(file_hit, JO)` = 0.36–0.58.

### 2.3 The judge rewards confident answers built on wrong evidence

Mean `judge_overall` split by whether retrieval found an expected file:

| Candidate | JO given hit | JO given **miss** | gap |
| --- | ---: | ---: | ---: |
| H12A + Gemini FL | 3.77 | **1.44** | 2.32 |
| H12B + Gemini FL | 3.91 | **2.16** | 1.75 |
| H13 + Gemma26 | 4.80 | **4.07** | 0.72 |
| H14 + Gemma26 | 4.88 | **4.05** | 0.83 |

When retrieval fails, Gemini Flash Lite is scored 1.4–2.2 and Gemma26 is scored
4.05. Concrete case `where-angular-cli`, where both failed retrieval:

- H12B (Gemini FL) correctly abstains — *"The provided repository context does not
  contain information regarding where the application wraps Angular CLI commands."*
  → scored `None`.
- H14 (Gemma26) fabricates a class `AngularCLIToolWrapper` in
  `src.automation.wrappers` with an invented command list → scored **3.25 / 5**.

The same judge awarded H14+Gemma26 a **perfect 4.00/4 on
`judge_hallucination_control`** — the exact criterion this case violates.
Note Gemma26 also has the best `citation_path_valid_rate` (0.996): the cited
paths *exist*, they just do not contain the answer. Path validity is being
mistaken for grounding.

### 2.4 ★Sum/24 carries about one criterion of information

Mean off-diagonal inter-criterion correlation per candidate: 0.56, 0.60, 0.68,
0.69, 0.78, 0.81. The six criteria are not independent — summing them inflates
apparent precision. This is the same halo/ceiling failure already documented for
the explanation judge in `.session/2026-06-10_judge-metascore-report.md`
(all candidates at median 5.0/5.0); the strict prompt compressed the ceiling but
did not remove the halo.

**Net:** the recorded decision "do not promote H14+Qwen4B" is correct, but the
reason on file (★Sum 19.13) is not the real reason. And the corollary conclusion —
that H14+Gemma26 is the best local setup — is not supported by this data.

---

## 3. Measurement gaps found

1. **The headline metric understates the real bottleneck by ~25pp.** 62% of
   protogen cases have 2–3 expected files (distribution: 38x1, 61x2, 1x3), but
   `file_hit` counts a case as a hit on **one** match. For H14+Gemma26:
   `file_hit` 0.84, all expected files in top-10 **68/100**, all expected files
   present in the 4 files actually fed to the model **59/100**. That 0.59 is the
   ceiling on answerability and it appears on no leaderboard.
2. **The reranker under-fills and the metrics hide it.** `rerank_limit: 10`, but
   the selection count distribution is median 5 — 10 items in only 17/100 cases,
   as few as 2. Slots 6–10 are deterministic backfill, so `@10` figures largely
   measure the deterministic path, not the reranker.
3. **The rerank contribution is small.** Of H14+Gemma26's 84 hits, 73 were already
   in the deterministic top-10 and only 11 were rescued from rank ≥10. Losses
   (deterministic hits demoted out of the head) are not measured at all.
4. **Public benchmarks cannot measure bundles.** Every CodeSearchNet/SWE report has
   `expected_files_mean = 1.0` and `multi_expected_rate = 0.0`. Single-file ground
   truth cannot evaluate multi-file exploration, which is the product's purpose.
5. **H14 reproducibility is unverified at temperature 0.** The original
   H14+Gemma26 run scored 0.84 over 100 cases; the rerun partial sits at 0.706
   over 17 cases with 2 empty predictions. Small N, but it needs an explanation.
6. **Stale docs.** `docs/hypotheses/README.md` stops at H12 and omits H13/H14
   entirely; `docs/local-h13-h14-gemma26-2026-06-10.md` still calls the H14 clean
   rerun "pending" although a completed 100/100 run exists.

---

## 4. Two weak spots with opposite causes

| Benchmark | FH@1 | headroom@10 | coverage_gap@10 | Diagnosis |
| --- | ---: | ---: | ---: | --- |
| SWE-bench retrieval | 0.610 | **0.350** | 0.040 | Pure **ranking** problem — candidates are already in top-10 |
| CodeSearchNet PHP | 0.730 | 0.140 | **0.130** | Pure **recall** problem — the file never enters the candidate set |

Reranking is the fix for SWE and cannot help PHP. Indexing/embedding is the fix
for PHP and would barely move SWE.

**Route inversion — the strongest untested signal.** The `workflow` route is the
*best* bucket on CodeSearchNet Python (FH@1 0.896, 316 cases) and the *worst* on
SWE-bench (FH@1 0.563, 64 cases). Routing and weights calibrated on CodeSearchNet
are therefore mis-calibrated for real change-request queries. `semantic` is
consistently weakest (Python 0.787, PHP 0.654).

---

## 5. Experiments to run, in priority order

**E1 — Isolate the confound with a 2x2 grid (retrieval x answer model).**
Two cells exist; two are missing: `H12B retrieval + Gemma26 answer` and
`H14 retrieval + Gemini FL answer`. This settles whether the text graph or the
answer model produced the ★Sum lead. It also finally benchmarks the recorded
recommendation "H12B-style retrieval + qwen4b for generation only", which has
never actually been run. Requires decoupling the planner/reranker model from the
answer model in config — currently one `generation` block drives all three.

**E2 — Fix the judge before trusting any further ranking.**
- Add an explicit abstention rule: an answer citing existing-but-irrelevant files
  must score *below* an honest "not found". Today it scores ~2 points higher.
- Report the six criteria separately; stop publishing ★Sum/24 until inter-criterion
  r drops well below the current 0.56–0.81.
- Neutralize citation formatting (normalize answers to a fixed template before
  judging, or make format an explicit controlled variable).
- Anchor on ~30 hand-labeled cases. No judge revision should be adopted without
  human agreement numbers — two judge iterations have now each failed differently.

**E3 — Promote `context_bundle_complete` to the primary answer metric.**
Currently 59/100 versus a headline 0.84. Optimising `file_hit` is optimising the
wrong target for a multi-file question set.

**E4 — SWE-bench rerank + route-specific recalibration.** The largest untested
win on the board: 0.35 headroom, 0.04 coverage gap, and Gemini rerank has never
been run on SWE. Tests H7.7 (proposed, never executed) using the route inversion
above as the hypothesis.

**E5 — PHP recall.** Attack `coverage_gap@10` 0.13 with PHP-aware symbol
extraction and an embedding comparison for PHP file metadata. This is the only
real defect the multi-language sweep found.

**E6 — Ship the H7.3 gate.** Measured oracle reaches always-Gemini quality using
**5–11%** of rerank calls; the trained MLP gate spends 26–40% for less. It is
still an offline analysis script over saved outputs and was never integrated into
live search. Best cost/quality ratio available.

**E7 — Cheap fix: force full rerank output.** Require exactly `rerank_limit`
ranked items (or an explicit "no opinion beyond k"), so `@5`/`@10` measure the
reranker rather than deterministic backfill. Also add a rerank-loss counter
(deterministic top-10 hits demoted out of the head).

### Recommended default today

On the measured evidence, and pending E1:

```text
EmbeddingGemma-300M file-metadata index
  -> H6.1 calibrated hybrid file candidates + H7.2 query expansion   (780 ms, $0)
  -> gated LLM rerank, only on low-confidence cases                   (E6)
  -> answer model chosen separately from the retrieval stack          (E1)
```

H12B's deterministic single-query retrieval is the strongest answer-eval
configuration measured so far. The H13/H14 agentic planning + LLM rerank path
costs 3x the model calls and has not yet been shown to beat it on anything except
a judge metric that is biased toward its output formatting.
