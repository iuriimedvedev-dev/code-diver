# 2026-08-05 — H17 setup: corpus facts and one data-loss incident

## Incident — a 100-case judged baseline was silently overwritten

`.code-diver/reports/strict-judge/h14-qwen35-4b-answer-strict-qwen35-9b.json`
now holds **10 rows**, not 100. Clobbered Aug 4 23:56, seven minutes after the
10-case cache-verification run wrote
`protogen-h14-qwen35-4b-text-graph-10.json` at 23:49. The `.partial.json`
sibling was overwritten by the same rejudge, so the last recovery path went
with it.

Mechanism: the answer-run filename carries a case-count suffix (`-10` / `-100`)
and a budget suffix (`-cf10-cl160`), but the judged-output name inherits only
the budget suffix. Two different inputs mapped to one output. This is the same
class of defect I fixed in `run_h16_arm.sh` and did not check for on the
rejudge path.

**Damage: bounded, and no recorded conclusion is affected.** The un-judged
`protogen-h14-qwen35-4b-text-graph-100.json` (Jul 30, 100 rows) is intact and
carries every pre-registered metric. Its numbers reproduce the notes exactly —
`citation_expected_recall` 0.610, mean `duration_ms` 104 010. So H15, arm C and
arm D verdicts, all of which rest on deterministic metrics, stand unchanged.
What is lost is `judge_*` for that one run — the metric Findings 5 and 13
already removed from ranking. Regenerable by rejudging the intact report if
ever needed; not worth GPU time now.

How I found it: not by noticing, but because the fixed `compare_arm_runs.py`
printed `matched cases: 10` on a comparison that should have matched 100. The
detection was luck downstream of unrelated work. Worth making non-luck — a
report-integrity assertion (expected row count) would have caught it at write
time.

## `compare_arm_runs.py` fixed

Two defects, both closed:
- `citation_expected_recall` — the pre-registered **primary** metric — was
  absent from `DEFAULT_METRICS` entirely. Now reported first, through the
  continuous-metric path (paired-difference CI, not the binary sign test).
- The footer advised ranking on `answer_grounded` + `citation_fabricated_rate`,
  contradicting the H15 pre-registration. Rewritten to the actual commitment.

Metrics now carry role labels: `(primary)`, `(guardrail)`, `(mechanism)`,
`(continuity — not for ranking)`. 18 tests pass.

## Corpus — the scanner fix is clean, but the target repo drifted

Fresh index: **8 843 items / 3 842 paths / 19.83 MB content**, against the old
47 085 items / 22 578 paths / ~61.4 M chars. Build time ~1.5 min.

I suspected my exclusion-predicate unification had loosened something, because
first-party paths rose 3 529 → 3 842. **That suspicion was wrong.** Verified
against the full 28 382-file raw `rg` listing: every path the old matcher
excluded, the new one still excludes; the new matcher additionally excludes
24 255 `templates/frontend/node_modules/**` files that the old root-anchored
`fnmatch` missed. Old set ⊂ new set, zero removals. Pure fix.

The +313 is **repo drift**. The old catalog was built 2026-06-10; `protogen`
has since gained an untracked `team-configurator/` sub-project (306 files) plus
7 backend/test files, all mtimes 2026-07-10 … 2026-07-29. None of the 313 match
any `DEFAULT_EXCLUDES` pattern under either matcher. Doc/code split confirms
it: 3 004 + 300 = 3 304 code, 525 + 13 = 538 doc, exactly the observed
composition, and no existing path changed classification.

Method note for next time: to compare scanner behaviour in isolation the
baseline must be a fresh scan at the *current* repo state with the *old* code —
not a catalog built seven weeks ago. I compared across two variables and
briefly read the result as one.

## New corpus hazard: near-duplicate first-party code

164 of the 313 new files are under `team-configurator/release/`, a build-output
tree containing a source snapshot — e.g.
`release/team-configurator-macos-arm64/source/team-configurator/server/src/api.ts`
duplicating `team-configurator/src`. The index now holds near-duplicates of
first-party code.

This is worse for retrieval than the vendor tree was. Vendor was obviously
foreign and cheap to exclude; a duplicated copy of the project's own code
competes for the same candidate-pool slots as the original and is not
distinguishable by content. Candidate for exclusion — **not now**: changing the
corpus mid-series costs comparability again.

## Experiment isolation for H17

Two collections built from one repo snapshot, differing in exactly one field:

| collection | `max_input_chars` | items | paths | content |
|---|---|---|---|---|
| `code_diver_h17_ctrl` | 400 | 8 843 | 3 842 | 19.83 MB |
| `code_diver_h17_emb1200` | 1200 | 8 843 | 3 842 | 19.83 MB |

Composition identical to the item (`doc_chunk=1159, doc_manifest=538,
doc_summary=538, file_manifest=3304, file_summary=3304`), so the ctrl↔emb1200
contrast is causally clean.

The H14→ctrl contrast is **not** clean — it bundles vendor removal, the head
line/block caps, and 313 new files. Descriptive only.

`code_diver_h14_gemma26_text_graph` left untouched for comparability with all
prior runs.

## H17 result — the hypothesis is refuted

Replay of the same 398 persisted probe queries (from
`protogen-h14-qwen35-4b-text-graph-100.json`) against each collection.

| k | H14 | ctrl | emb1200 | nocaps |
|---|---|---|---|---|
| 1 | 0.166 | 0.178 | 0.184 | 0.178 |
| 5 | 0.454 | 0.479 | 0.497 | 0.479 |
| 10 | 0.595 | 0.656 | 0.681 | 0.656 |
| 20 | 0.742 | 0.761 | 0.785 | 0.761 |
| **34** | 0.791 | **0.865** | 0.859 | 0.865 |
| 60 | 0.853 | 0.896 | 0.926 | 0.896 |

**`max_input_chars` 400 → 1200 does nothing.** Paired, n=100:

| depth | Δ recall | 95% CI | up/down/same | p |
|---|---|---|---|---|
| 34 | −0.020 | [−0.062, +0.022] | 4 / 5 / 91 | 1.00 |
| 60 | +0.030 | [−0.011, +0.071] | 7 / 2 / 91 | 0.18 |

Both null. The apparent k-curve advantage rests on 7–9 discordant pairs out of
100 — at 91 unchanged cases the power is negligible. `emb1200` also costs 3x
the index build (4:06 vs 1:20). **Keep 400.**

Note the sign flip between k=34 and k=60. A non-monotonic "effect" across
depths on the same data is what a null looks like when read one depth at a
time; had I only run k=60 I would have had a +0.030 story to tell.

## Finding 17 — the head caps did nothing; vendor was the whole effect

`nocaps` (vendor excluded, 400 chars, caps disabled at 1e6) reproduces `ctrl`
**exactly** — 0.865 at k=34 and identical values at all six depths. Content
20.07 MB vs 19.83 MB: the caps truncated 240 KB of 20 MB, ~1.2%.

So the +0.085 / +0.120 is **vendor removal**, and my arithmetic dismissing that
was wrong. I had reasoned: vendor is 3.9% of the 34-pool ≈ 1.3 slots; H14's own
curve prices a slot at 0.0024 recall; therefore vendor ≈ +0.003, so it must be
something else.

That model counts only **displacement** — it assumes the ranking is fixed and
asks how many freed slots there are. The channel it misses is **corpus
statistics**. `hybrid_lexical_index.py:50-53` is BM25:

```python
document_frequency = len(self.item_ids_by_term.get(term, set()))
idf = math.log(1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
score += idf * ((tf * (k1 + 1)) / denominator)
```

`total_documents` went 47 085 → 8 843, every term's document frequency changed,
and the length normalisation in `denominator` uses a corpus mean that vendor
skewed. Removing vendor **rescores every candidate**, it does not merely free
slots.

This corrects a claim I made twice earlier in the series: that vendor was a
latency/size problem and not a quality problem. I supported it by measuring
vendor's *share of the pool*, which measures displacement only. The harm was
upstream of the pool, in the statistics that build it.

**Consequence for the near-duplicate `team-configurator/release` tree:** it is
more dangerous than 164 files suggests. A duplicated copy of first-party code
doubles the document frequency of exactly the terms that identify the original,
depressing their IDF. That is the same channel, pointed at our own code.

## Not isolated: vendor vs. corpus drift

ctrl differs from H14 by vendor removal AND 313 drifted-in files. The caps are
now excluded as a cause but drift is not. Drift adds 3.5% more documents and
should be neutral-to-negative, so vendor almost certainly dominates — but that
is an inference, not a measurement. Isolating it would need a current-snapshot
build with vendor deliberately re-included (~47k items, expensive) and would
change no decision: the lean index wins on both quality and latency regardless.

## Latency, replayed retrieval only

1.866 → 0.522 s/case, 3.6x. On top of the profile-cache win, not instead of it.

## End-to-end confirmation — 100 cases on the ctrl collection

`protogen-h17-ctrl-qwen35-4b-100.json`, 100/100, 0 errors, matched pairs
against the intact `protogen-h14-qwen35-4b-text-graph-100.json`. Only the
collection differs; every CLI flag matches H14.

| metric | H14 | ctrl | Δ | |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.610 | 0.660 | **+0.050** | CI [−0.010, +0.110] |
| `citation_fabricated_rate` (guardrail) | 0.054 | 0.040 | −0.014 | improves |
| `candidate_file_recall` | 0.715 | 0.765 | +0.050 | |
| `candidate_bundle_complete` (mechanism) | 0.620 | 0.660 | +0.040 | p = 0.50 |
| `context_bundle_complete` | 0.460 | 0.530 | +0.070 | p = 0.14 |
| s/case | 104.0 | **52.1** | −50% | |

**By the pre-registration this is not a confirmed quality win** — the primary
metric's CI includes zero. Stated plainly because every metric moving the right
way makes it tempting to call +0.050 a result.

Adopt anyway, on different grounds: it is a **strict Pareto improvement**.
Nothing regresses, the guardrail improves, and latency halves. Every other
lever in this series bought quality with time; this one buys both. `ctrl` is
the new baseline.

52.1 s/case also confirms Finding 16's ~51 s projection.

## Transfer rate: pool +0.085 → citations +0.050 (~59%)

Consistent with Finding 10 and H15. Delivering the file to the pool is
necessary, not sufficient — roughly four of every ten newly-found files still
go uncited. That residual is a generation problem, not a retrieval one, and no
further retrieval work addresses it.

## Revised Pareto frontier

| config | `citation_expected_recall` | s/case |
|---|---|---|
| H14 cf4 (old index) | 0.610 | 104.0 |
| **ctrl cf4 (lean index + profile cache)** | **0.660** | **52.1** |

Headroom visible in the replay: pool recall is 0.865 at depth 34 and 0.896 at
60, so arm B (deeper cut) has +0.031 of pool to convert — at the ~59% transfer
rate, ~+0.018 of primary. H15's context widening (+0.055 for +8.5% latency)
remains untested on top of the new baseline; its gain and ctrl's may not be
additive, since both act on the same missing-second-path population.

## Finding 18 — H15 replicates on the new baseline, and this time it is confirmed

`protogen-h17-ctrl-qwen35-4b-100-cf10-cl160.json`, 100/100, 0 errors. Only
`--context-files` differs from the ctrl baseline.

| metric | ctrl cf4 | ctrl cf10 | Δ | |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.660 | **0.715** | **+0.055** | CI [+0.018, +0.092] |
| `citation_fabricated_rate` (guardrail) | 0.040 | 0.025 | −0.015 | improves |
| `context_bundle_complete` | 0.530 | 0.670 | +0.140 | 14/0, p = 0.0001 |
| `candidate_bundle_complete` (mechanism) | 0.660 | 0.670 | +0.010 | 1/0 |
| `answer_grounded` (continuity) | 0.750 | 0.820 | +0.070 | p = 0.065 |
| s/case | 52.1 | 66.7 | +27.9% | |

**The CI excludes zero.** This is the first confirmed win on the pre-registered
primary metric in the series. H15 found the same +0.055 but only post-hoc, on a
metric chosen after seeing a null; here `citation_expected_recall` was fixed
before any H16 arm ran. The effect replicated at the same magnitude on a
different index — that is the strongest evidence in this record.

Note the additivity: the two interventions did not overlap as feared. ctrl gave
+0.050 and cf10 gives +0.055 on top, total 0.610 → 0.715.

## The frontier, and it is no longer a trade

| config | `citation_expected_recall` | s/case |
|---|---|---|
| H14 cf4 | 0.610 | 104.0 |
| H14 cf10 | 0.665 | 112.9 |
| ctrl cf4 | 0.660 | 52.1 |
| **ctrl cf10** | **0.715** | **66.7** |

Both ctrl points **dominate** both H14 points — better and faster, not traded.
Against the series' starting point: +0.105 primary and −36% latency.

## Refuted en route: why cf10 costs more now

I proposed that widening cost more on the new baseline (+14.6 s vs +8.9 s)
because better retrieval fills the window more densely. The data refutes it:
mean `context_files_count` is 8.41 (H14 cf10) vs 8.49 (ctrl cf10) — effectively
identical fill. The extra cost is unexplained. These are single runs with no
repeats, so ordinary run-to-run variance is not excluded.

## Saturated again — the next binding constraint is depth

`context_bundle_complete` (0.670) has reached `candidate_bundle_complete`
(0.670) exactly, as it did in H15. The context window is no longer the
constraint; the candidate pool is. Replay says depth 60 holds 0.896 pool recall
against 0.865 at 34. Arm B is now the indicated next arm, and unlike before it
attacks the metric that is actually binding.

## Finding 19 — deepening the rerank pool is a confirmed degradation (H19 arm B)

Single-line change on top of the ctrl+cf10 champion: `llm_rerank.candidate_limit` 34 -> 60
(`configs/context-awareness/protogen-h19-depth60.yml`, line 117 — verified NOT the
`hybrid_search.candidate_limit` at line 67). 100/100 cases, 0 errors.

| metric | depth 34 (champion) | depth 60 | delta | |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.715 | 0.670 | **-0.045** | CI [-0.089, -0.001] |
| `citation_fabricated_rate` (guardrail) | 0.025 | 0.035 | +0.011 | worsens |
| `candidate_file_recall` | 0.770 | 0.745 | -0.025 | |
| `candidate_bundle_complete` (mechanism) | 0.670 | 0.640 | -0.030 | 2up/5down, p=0.45 |
| `context_bundle_complete` | 0.670 | 0.640 | -0.030 | 2up/5down, p=0.45 |
| `answer_grounded` (continuity, not for ranking) | 0.820 | 0.770 | -0.050 | 3up/8down, p=0.23 |
| s/case | 66.7 | 74.9 | +12.4% | |

The primary metric's CI excludes zero on the negative side. This is the series' first
*significant negative* on the pre-registered primary. Every metric moves the wrong way
and the guardrail worsens. Rejected.

**Mechanism — the decisive evidence is the divergence between two measurements of the
same pool.** Probe replay on the ctrl index shows the depth-60 pool objectively contains
MORE expected paths than the depth-34 pool: recall@60 = 0.896 vs recall@34 = 0.865
(+0.031). Yet `candidate_file_recall` — the share of expected paths surviving the
reranker into the top-10 — FELL, 0.770 -> 0.745. More going in, less coming out. The
4B reranker's selection quality degrades with input size faster than it gains from
input completeness. Prompt grew to roughly 27k tokens at depth 60.

**Prediction error, recorded.** I pre-registered +0.018 before the run. Wrong in sign.
The prediction silently assumed rerank quality is independent of input size; the ~59%
pool->top-10 transfer rate I extrapolated from was measured at FIXED reranker input
(34), so it could not be applied to a changed input size. Rate constants measured under
one setting are not portable to the setting being changed — this is the same class of
error as the per-slot displacement arithmetic in Finding 17.

**Consequence for the loss decomposition.** The pool is no longer the binding
constraint, and it is not convertible by supplying more of it. At pool 0.896, citation
lands at 0.670: reranker + generation together lose 22.6 pp while retrieval loses 10.4.
The reranker's *capacity*, not the pool's *contents*, is the constraint.

**Follow-on hypothesis (H19 arm D), running.** If 60 is worse than 34, the optimum may
lie below 34. `configs/context-awareness/protogen-h19-depth20.yml` = ctrl with
`llm_rerank.candidate_limit: 20`. Replay bounds the cost: pool recall@20 = 0.761 vs
0.865 at 34, so arm D discards 10.4 pp of reachable pool. It wins only if the smaller
prompt buys back more than that in selection quality. Unlike every prior arm this one
is also *faster*, so a null on quality is still a Pareto move. Pre-registered
prediction, before the result: primary between 0.68 and 0.72 — i.e. I expect the
pool loss to roughly cancel the selection gain, most likely a small net negative
(~-0.015), with latency around 58-62 s/case.

## Finding 20 — the rerank-depth axis has an interior optimum at ~34; axis closed

Arm D: `llm_rerank.candidate_limit` 34 -> 20 (`protogen-h19-depth20.yml`, line 117
verified; line 67 hybrid stays 360). 100/100 cases, 0 errors.

| metric | depth 34 (champion) | depth 20 | delta | |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.715 | 0.680 | -0.035 | CI [-0.080, +0.010] |
| `citation_fabricated_rate` (guardrail) | 0.025 | 0.031 | +0.006 | CI [-0.014, +0.027] |
| `candidate_file_recall` | 0.770 | 0.735 | -0.035 | CI [-0.077, +0.007] |
| `candidate_bundle_complete` (mechanism) | 0.670 | 0.630 | -0.040 | 2up/6down, p=0.29 |
| `answer_grounded` (continuity) | 0.820 | 0.790 | -0.030 | 3up/6down, p=0.51 |
| s/case | 66.7 | 57.6 | **-13.7%** | |

Prediction check: I pre-registered 0.68-0.72, point ~-0.015, latency 58-62 s. Outcome
0.680 (bottom edge), -0.035 (2x my point estimate), 57.6 s (just under). Direction and
interval right, point estimate too optimistic.

**My pre-registered acceptance rule was wrong and I am not applying it.** I wrote
"accept if the primary CI does not exclude zero on the negative side AND latency drops."
That treats failure-to-reject as evidence of equivalence. With n=100 the CI half-width
is +/-0.045, so this design *cannot* distinguish "no loss" from "a 3.5 pp loss" — the
rule would have rubber-stamped any degradation smaller than the noise floor. Correct
reading: depth 20 buys 9.1 s/case for an estimated 3.5 pp of recall, plausibly up to 8.

**The mechanism, now quantified.** Pool recall (probe replay, ctrl index) against
post-rerank recall gives a transfer rate that declines monotonically with reranker
input size:

| depth k | pool recall@k | `candidate_file_recall` | transfer |
|---|---|---|---|
| 20 | 0.761 | 0.735 | **96.6%** |
| 34 | 0.865 | 0.770 | **89.0%** |
| 60 | 0.896 | 0.745 | **83.1%** |

Post-rerank recall is the product of a rising factor (pool completeness) and a falling
one (selection quality). Marginal steps:
- 20 -> 34: pool +0.104, transfer -0.076 => product **+0.035**
- 34 -> 60: pool +0.031, transfer -0.059 => product **-0.025**

The product peaks between 34 and 60, near 34. A finer probe (42-45) would move the
primary by well under 0.01 — unresolvable at n=100 and not worth ~100 GPU-minutes.
**Axis closed. Depth stays 34.**

This also retires the "give the retriever more room" family of interventions. Three
separate arms (emb1200, nocaps, depth60) all failed for the same underlying reason:
the 4B reranker is capacity-limited, so enlarging what it must read costs more than
the extra material returns.

## Pareto frontier as of arm D

| config | primary | s/case | status |
|---|---|---|---|
| ctrl cf4 | 0.660 | 52.2 | **frontier** (cheapest) |
| ctrl cf10 depth20 | 0.680 | 57.6 | **frontier** |
| ctrl cf10 depth34 | 0.715 | 66.7 | **frontier** (best quality) |
| ctrl cf10 depth60 | 0.670 | 75.0 | dominated |
| H14 cf10 | 0.665 | 112.9 | dominated |
| H14 cf4 (series start) | 0.610 | 104.0 | dominated |

Net movement of the series: +0.105 primary at -36% latency versus the starting point.

**Next axis: generation.** Retrieval-side levers are exhausted. At depth 34 the pool
holds 0.865, top-10 holds 0.770, and citation lands at 0.715 — so ~7 pp is lost between
"the file is in the context window" and "the model cites it", on top of the 9.5 pp lost
at rerank. The open question stated earlier still stands: when the model HAS the
expected file in context and does not cite it, is that a prompt problem, a
context-ordering problem, or a 4B capability limit? Needs user direction before opening.

## Finding 21 — Gemma-4 E2B: halves latency, quadruples fabrication. Rejected on the guardrail.

`protogen-h20-e2b.yml` = champion with `generation.model` -> `mlx-community/gemma-4-e2b-it-4bit`.
NOTE: `llm_rerank` has no `model` field of its own and falls back to `config.generation`, so
this swap changes query expansion + rerank + answer generation together (same coupling as the
earlier H14 gemma runs, so those remain comparable). 100 cases, 98 matched (2 E2B rows had
empty prediction / zero context).

| metric | qwen35-4b | gemma-e2b | delta | |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.730 | 0.587 | -0.143 | CI [-0.227, -0.059] |
| `citation_fabricated_rate` (guardrail) | 0.025 | 0.102 | **+0.077** | CI [+0.033, +0.121] |
| `candidate_file_recall` | 0.786 | 0.750 | -0.036 | CI [-0.107, +0.036] |
| `candidate_bundle_complete` | 0.684 | 0.633 | -0.051 | 8up/13down, p=0.38 |
| `answer_grounded` (continuity) | 0.837 | 0.653 | -0.184 | 5up/23down, p=0.0009 |
| s/case | 66.7 | 32.1 | **-52%** | |
| hard errors | 0 | 2 | | |

**Rejected.** The guardrail's CI excludes zero: fabrication quadrupled. The H15
pre-registration says the guardrail must not worsen regardless of the primary result, and
bending it for an attractive latency number is exactly the case the rule was written for.
On (quality, latency) alone the point is non-dominated (0.575 @ 32.2 s is the new cheapest
corner), but fabricated file references are a trust failure for a code-search tool, not a
metric trade. E4B not run: on H14 it was both worse and slower than E2B (0.430 @ 89.7 s vs
0.460 @ 74.0 s), and it does not address fabrication.

Worth recording: E2B is much better here than in its H14 run (0.575 vs 0.460), so the index
and config gains transferred across model families.

**Actionable spin-off — the reranker is model-insensitive, the generator is not.**
`candidate_file_recall` fell only 0.036 with a CI covering zero, i.e. E2B ranks nearly as
well as qwen35-4b; the entire significant loss is downstream of ranking. E2B's retrieval
leg cost 21.8 s vs qwen's 27.9 s. So E2B-for-rerank + qwen35-4b-for-answer should save
roughly 6 s/case at no measured ranking cost and no fabrication penalty. Blocked by
`LlmRerankConfig` having no `model`/provider override — it silently inherits
`config.generation`. Decoupling the rerank model from the generation model is the
prerequisite, and it is the same class of design defect as the overloaded `neighbor_limit`:
one config knob standing in for two independent decisions.

## Graph audit (CPU-only, no GPU cost)

Facts established on the ctrl artifact (17,364 edges / 8,843 items / 3,842 files):

- **Latency: the graph is not the cost.** Warm per-query stage timings — embedding call
  8.7 ms, + Qdrant multi-index vector 143.6 ms, + BM25/fusion 181.3 ms, + graph_file total
  179.8 ms, of which `_propagate` itself is **0.4 ms**. Catalog load 48 ms, once. The whole
  retrieval stack is ~0.5 s/case against 66.7 s end-to-end: **99.3% of wall-clock is local
  4B inference**, and specifically prompt ingest at ~700-800 tok/s (three independent
  estimates agree: cf4->cf10 = +15.1 s for ~12k tokens; depth 34->60 = +8.8 s for ~6k).
- Edge composition: `imports` 5,644 + `references` 4,401 are cross-file (collapse to 3,854
  unique file pairs); `summarizes` 5,622 + `same_file_next` 1,697 are intra-file and are
  dropped by `FileGraphAdjacencyIndex.from_item_paths_and_edges` (source==target). That is
  42% of the artifact inert on the graph_file path — but NOT removable, since the item-level
  strategies (`GraphCandidateExpander`) do use them.
- Adjacency IS symmetrized (reverse edge at weight x0.7), so "who imports me" is reachable.
  An earlier worry about directionality is withdrawn.
- **Connectivity is the strongest prior in the series**: 96.3% of the 163 expected answer
  paths are graph-connected vs a 49.7% corpus base rate; expected-path degree 7.50 mean /
  4 median vs corpus 2.00 / 0. So `graph_weight: 0.45` is not absurd. My earlier
  "heavy weight on a thin graph -- suspicious" remark was wrong and is withdrawn.
- Isolation does not hurt recall: isolated expected paths were cited 5/6 (83%) vs 67.5% for
  connected ones. They are distinctive filenames (`pyproject.toml`, `logging_config.py`,
  `feature_flags.py`) that path/lexical scoring finds without help.
- **But the graph does not help where we fail**: MISSED expected paths have HIGHER degree
  than cited ones (8.73 vs 6.93 mean).
- "graph_score has degenerated into a popularity prior" -- tested and only PARTIALLY
  supported, so not claimed. Spearman between graph_score rankings from disjoint random
  140-file seed sets = 0.396 (min 0.255, max 0.553, 28 pairs); Spearman vs plain degree =
  0.406; only 53 files scored in all 8 trials. So ~40% static, ~60% query-conditioned.
  The degree/miss correlation is therefore more likely confounded by case difficulty
  (high-degree files are central modules whose questions have multi-file answers).

Code defects found, ranked by value:

1. **`neighbor_limit` is overloaded** (`graph_file_retrieval_strategy.py:151` and `:160`) --
   it caps neighbors per node AND the frontier width per level. The per-node cap never
   binds (max degree 31 < 40); the frontier cap binds hard. The frontier cannot be tuned
   without changing neighbor semantics. -> task #11.
2. **Three divergent propagation implementations**: `GraphFileRetrievalStrategy._propagate`
   (our path), `FileGraphAdjacencyIndex.expand`, `GraphCandidateExpander.expand`.
3. `_propagate` lacks the `best_seen` revisit guard the other two have. Measured cost on
   this corpus is small: 26 of 40 frontier slots per level are spent on already-better-scored
   nodes, yet reach is 607 vs 612 files (5 files, <1%). Efficiency, not a quality bug.
4. **NOT a bug -- do not "fix"**: the decay off-by-one (`decay**(depth+1)` in `_propagate`
   vs `decay**depth` in the other two) is a no-op, because `_normalize` is min-max and
   invariant to a uniform factor, and the between-hop ratio is 0.65 in both.

## Finding 22 — graph_weight sweep: the graph is worth +0.080 pool recall, and 0.45 sits on a cliff edge

Replay sweep over `graph_file_search.graph_weight`, fixed probe queries from the champion
report, 100 cases, ~50 s per config, no answer generation. Exactly one config line changed
per arm (line 110, `graph_file_search`; line 74 `hybrid_search.graph_weight` is 0.0 and
untouched).

| graph_weight | pool_recall@34 | pool_bundle_complete | marginal |
|---|---|---|---|
| 0.00 | 0.785 | 0.730 | — |
| 0.15 | 0.865 | 0.820 | **+0.080** |
| 0.30 | **0.871** | 0.820 | +0.006 |
| 0.45 (current) | 0.859 | 0.820 | -0.012 |
| 0.60 | 0.810 | 0.750 | -0.049 |
| 0.80 | 0.761 | 0.680 | -0.049 |

Shape: sharp rise, wide plateau, cliff.

1. **The graph contributes +0.080 pool recall@34** (0.785 -> 0.865). That is the single
   largest retrieval-side contribution measured in this series, on par with the lean-index
   gain (+0.085). The graph is load-bearing, not decoration.
2. **Nearly all of it is captured at weight 0.15.** 0.15/0.30/0.45 give 0.865/0.871/0.859 --
   indistinguishable (0.012 spread is ~2 expected paths of 163) and `pool_bundle_complete`
   is *identical* at 0.820 for all three.
3. **The defect is placement, not magnitude.** 0.45 sits on the upper edge of the plateau,
   immediately before the cliff (0.60 loses 0.049). The weight is ~3x larger than needed to
   capture the benefit and buys no margin. 0.30 delivers the same measured quality from the
   middle of the plateau.

**Not treated as a win.** 0.871 vs 0.859 is ~2 paths, unresolvable; and Findings 19/20
established that pool gains do not transfer monotonically through the reranker. A +0.012
pool delta would yield at most ~+0.011 post-rerank against a +/-0.045 CI half-width, so a
100-minute confirmation run is not justified by the quality argument.

**Decision: champion stays at 0.45** (it is the only end-to-end-validated setting).
`graph_weight: 0.30` is banked as a robustness change to fold into the next full
re-validation that is being run for some other reason -- not worth a standalone run.
This also retires the "is 0.45 arbitrary?" question: it is defensible on quality, poorly
placed on robustness.

## Finding 23 — Qwen3.5 9B: no significant quality gain, 3.3x fabrication, +61% latency. Rejected.

`protogen-h22-qwen9b.yml` = champion with `generation.model` -> `Qwen3.5-9B-MLX-4bit`. 100/100, 0 errors.

| metric | 4B-OptiQ | 9B | delta | |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.715 | 0.740 | +0.025 | CI [-0.047, +0.097] -- covers zero |
| `citation_fabricated_rate` (guardrail) | 0.025 | 0.083 | **+0.058** | CI [+0.025, +0.092] -- excludes zero |
| `candidate_file_recall` | 0.770 | 0.790 | +0.020 | CI [-0.045, +0.085] |
| `candidate_bundle_complete` | 0.670 | 0.700 | +0.030 | 12up/9down, p=0.66 |
| `answer_grounded` (continuity) | 0.820 | 0.730 | -0.090 | 6up/15down, p=0.078 |
| s/case | 66.7 | 107.3 | **+61%** | |

Rejected on all three counts: the primary gain is not resolvable, the guardrail significantly
worsens, and it costs 61% more time.

**Two of my predictions were wrong here, and the second one matters more than the first.**
(a) Latency: I predicted 80-95 s, actual 107.3 -- I again transported a ratio (125/104 = 1.20
from H14) across a regime change (H14 was cf4; cf10 doubles the prompt, and an ingest-bound
system scales with model size *on the long prompt*). Third occurrence of this same error class
in the series (see Findings 17, 19).
(b) Guardrail: I predicted fabrication BELOW 0.025 on the reasoning that "fabrication is a
function of model size" -- the explanation I gave for E2B's 0.102. **That explanation is
refuted.** Fabrication is NON-MONOTONIC in size:

| model | fabrication | primary | s/case |
|---|---|---|---|
| gemma-4-e2b (2B eff.) | 0.100 | 0.575 | 32.2 |
| **qwen3.5-4B-OptiQ** | **0.025** | 0.715 | 66.7 |
| qwen3.5-9B | 0.083 | 0.740 | 107.4 |

Both the smaller and the larger model fabricate 3-4x more than the champion. So the champion's
0.025 is not a scale effect -- it is a property of that specific model/quantization, and it is
an outlier in our favour. This makes the 4B-MLX-4bit control (same architecture, same size,
plain quantization instead of OptiQ) the most informative arm remaining, not the throwaway I
scheduled it as. Interim at 67 matched cases: 4B-plain micro-recall 0.618 vs champion 0.673 on
the same 67 cases, i.e. plain 4-bit is tracking ~0.055 WORSE -- suggesting OptiQ is doing real
work. Final pending.

## Loss decomposition, corrected (champion, 100 cases)

| stage | value | loss |
|---|---|---|
| all expected paths | 1.000 | |
| in candidate pool @34 | 0.865 | **-13.5 pp** (largest bucket) |
| survive rerank into top-10 | 0.770 | -9.5 pp |
| actually cited | 0.715 | -5.5 pp |

Correction to an earlier statement in this file: generation is NOT the dominant remaining loss.
Once an expected file reaches the context window it gets cited 92.9% of the time (0.715/0.770).
The largest remaining bucket is the **pool blind spot**: 13.5 pp of expected files never enter
the candidate pool at all, and deepening to k=60 only recovers to 0.896 (10.4 pp) while making
the end-to-end result worse (Finding 19). So the question is not pool *size* but pool *contents*.

## Finding 24 — the guardrail advantage comes from the OptiQ QUANTIZATION, not from scale or architecture

`protogen-h22-qwen4b-plain.yml` = champion with `generation.model` -> `Qwen3.5-4B-MLX-4bit`.
Same architecture, same parameter count, same 4-bit budget; only the quantization method differs.
100 cases, 99 matched.

| metric | 4B-OptiQ | 4B-plain | delta | |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.717 | 0.687 | -0.030 | CI [-0.093, +0.032] |
| `citation_fabricated_rate` (guardrail) | 0.025 | 0.068 | **+0.043** | CI [+0.009, +0.077] |
| `candidate_file_recall` | 0.768 | 0.727 | -0.040 | CI [-0.098, +0.017] |
| `candidate_bundle_complete` | 0.667 | 0.596 | -0.071 | 3up/10down, p=0.092 |
| `answer_grounded` (continuity) | 0.818 | 0.687 | -0.131 | 6up/19down, p=0.015 |
| s/case | **66.7** | 71.1 | +6.6% | |

Fabrication across every model tested on the champion config:

| model | fabrication | primary | s/case |
|---|---|---|---|
| gemma-4-e2b-4bit | 0.100 | 0.575 | 32.2 |
| qwen3.5-9B-MLX-4bit | 0.083 | 0.740 | 107.4 |
| qwen3.5-4B-MLX-4bit | 0.068 | 0.687 | 71.1 |
| **qwen3.5-4B-OptiQ-4bit** | **0.025** | 0.715 | 66.7 |

Every non-OptiQ artifact lands in 0.068-0.100. OptiQ alone sits at 0.025 -- 2.7-4x better -- and
is also FASTER than plain 4-bit, so it dominates on all three axes. With architecture and size
held fixed, this attributes the effect to the quantization method.

**Two of my explanations are now refuted, in sequence.** I first attributed E2B's 0.100 to model
size; 9B (0.083) refuted the scale story; 4B-plain (0.068) refutes the architecture story too.
The cause is the quantization artifact.

**Uncomfortable implication: the 0.025 guardrail is partly luck of artifact choice.** Had the
series started on `MLX-4bit`, the baseline would have been 0.068, and we would likely have
concluded that fabrication at that level is simply what local 4B models do -- and would NOT have
rejected E2B (0.100) or 9B (0.083) on the guardrail. The guardrail's discriminating power depends
on a baseline we picked for unrelated reasons. Worth remembering before treating any guardrail
threshold as a property of the task rather than of the setup.

**New cheap high-information experiment this finding creates:** `mlx-community/gemma-4-e4b-it-OptiQ-4bit`
exists on the server. If the mechanism is OptiQ, its fabrication should drop far below the 0.100
of gemma-4-e2b-4bit. That is a direct test of the just-discovered mechanism AND the only remaining
candidate that could be both fast (the gemma-4 E-family ran at 32 s/case for E2B) and well-grounded.
Not launched -- awaiting user direction.

---

## Finding 25 -- the pool blind spot is NOT one mechanism, and I could only name half of it

All 22 expected paths that never enter the pool (13.5 pp, 17/100 cases) **are present in the
index** -- every one carries both a `file_manifest` and a `file_summary` item. So this is not an
indexing gap. Something ranks them out.

**Low IDF explains a tail, not the bulk.** Corrected measurement (my first pass had a
tokenisation bug: I split the corpus on non-alphanumerics but looked up whole underscored stems,
so every compound name falsely reported `content_df=0`):

| | MISSING (n=22) | FOUND (n=141) |
|---|---|---|
| MIN token idf, mean / median | 2.112 / **2.415** | 2.483 / **2.466** |
| MEAN token idf, mean / median | 2.313 / 2.485 | 2.841 / 2.715 |
| MAX corpus df, median | 343 (**8.9%**) | 326 (**8.5%**) |

The medians are nearly identical; only the means diverge. That is a heavy tail, not a uniform
shift. Roughly 9 of the 22 have a genuinely non-discriminative name -- `config` (df 3433, 89.4%
of files), `app` (1568), `service` (989, x3), `session` (980), `frontend` (821) -- and for those
the corpus-wide-IDF channel of Finding 17 is a plausible cause. It does **not** explain
`src/eval/judge.py` (`judge` df=65, 1.7%), `src/pipeline/orchestrator.py` (`orchestrator` df=58,
1.5%) or `src/eval/runner.py` (`runner` df=89, 2.3%). Those names are highly distinctive and
still lost.

**The second mechanism is unidentified. Saying so instead of forcing the single-cause story,
because that pattern already produced two withdrawn explanations in this series (Findings 21, 24).**

## Finding 26 -- query expansion invents paths at scale; that is a real defect, but it is NOT the blind spot

24.4% of probe slots (99 of 398 in the champion report) contain a path-like token.
**78 of those 99 (79%) name a file or directory that does not exist in the repository.**

Examples, all from blind-spot cases:

| case | invented | reality |
|---|---|---|
| `where-eval-runner` | `evals/`, `app_platform/qa/`, `src/qa/` | the dir is `src/eval/` |
| `where-operator-registry` | `src/core/config.py get_settings`, `src/models/__init__.py SavedFilter` | from a different project; pool rank 1 became `templates/backend/src/core/config.py` |
| `where-pipeline-run` | `src/supervisor/execution.py`, `src/infrastructure/agent_executor.py` | pool filled with `src/agents/supervisor/*` |
| `where-eval-judge` | `site:apps/*/ .generation/agents/ui_designer_agent.md` | another repo's layout |

**But the corpus number does not support my first reading.** Among the 17 blind-spot cases, 9
(53%) contain an invented path, against a 48% base rate across all 100 cases -- no enrichment.
Case-mean pool recall is 0.865 with an invented path vs 0.904 without: right direction, but an
unpaired comparison on n=48/52 confounded by case difficulty. **I generalised from five vivid
anecdotes; the measurement cut it back to "pervasive defect, unproven cost."**

Method note: my throwaway count said 76/97, the committed script says 78/99. The draft applied
`rstrip('/')` before testing for a slash, so single-segment directory hints like `evals/` were
silently skipped -- the very token that started this investigation. `scripts/filter_hallucinated_path_probes.py`
is the correct version.

**Queued paired experiment (task #14):** replay pool recall with exactly those 78 slots dropped
and the other 320 kept. No case loses all its probes (kept-probe distribution 1:8, 2:13, 3:28,
4:51), so the arm is a clean one-change comparison. If pool recall rises, expansion's path
invention is net-negative -- and since expansion+rerank is 27.4 s of the 66.7 s budget, trimming
it would pay on both axes at once.

## Task #12 done -- the rerank stage can now run its own model

`llm_rerank.generation` is an optional `GenerationConfig` that inherits every unset key from the
app-level `generation` block, so YAML usually names only `model:`. Wired at both
`graph_file_rerank` and `hybrid_rerank` sites in `RetrievalStrategyFactory`. 957 unit tests pass,
including four new ones.

**I first implemented this as a bare `llm_rerank.model: str` and reverted it.** The codebase
already had this exact concept under `ExperimentHypothesisConfig.rerank_generation` -- a full
`GenerationConfig` override -- but only on the agentic search-tool path, not on the retrieval
strategy the champion uses. Shipping a second spelling of one idea is the tech debt the standards
forbid, so the narrower field went away.

**That choice then turned out to be load-bearing, for a reason I had not anticipated.**
`mlx_lm server` keeps one model resident and loads by id, so a rerank model that differs from the
generation model would force two model loads per case -- slower, not faster. The small model needs
its own server on its own port, which means the override must carry `url`, not just `model`. The
bare-`model` version would have been unusable for the experiment it was built for.

## Task #11 done -- `neighbor_limit` no longer means two different things

`_propagate` used one knob for two unrelated quantities: the per-node edge cap (line 151) and
the per-level frontier width (line 160). On this graph the per-node cap never binds -- the
busiest file has 31 edges against a limit of 40 -- so `neighbor_limit: 40` was in practice a
pure level-width setting, and nobody reading the config could tell.

`graph_file_search.frontier_limit` now names the level width. Unset means "reuse
`neighbor_limit`", so **the champion is bit-identical**: it declares `neighbor_limit: 40` and no
`frontier_limit`, and the fallback reproduces the old code path exactly. 961 unit tests pass,
including four new ones; the pair of propagation tests show `frontier_limit: 2` yielding two
second-hop files where the default yields five, with `neighbor_limit: 10` held above the hub's
degree so per-node fan-out provably does not bind.

The `best_seen` revisit guard that `FileGraphAdjacencyIndex.expand` and `GraphCandidateExpander`
both have is still absent here -- deliberately left for later, since it changes results rather
than just naming them. The decay off-by-one between the three implementations stays untouched:
Finding 21 established it is a no-op under min-max normalisation.

This is now a real axis to sweep: `frontier_limit` was never varied independently, and the
graph channel contributes +0.080 pool recall (Finding 22), so the level width is plausibly worth
more than the rerank depth that has already been exhausted.

## Finding 27 -- half the blind spot sits one graph hop from material the retriever already ranked

Direct-edge analysis of the 22 missing paths against `.code-diver/protogen-h17-ctrl.json`:

- **None is graph-isolated.** Every one has degree >= 1 (mean 7.6, median 4).
- **Degree does not distinguish them.** Found expected paths average degree 7.5, missing 7.6.
  Another candidate channel refuted.
- **Only 1 of 22 has a direct edge to the co-expected path that WAS found** (`where-live-updates`).
  So within blind-spot cases the two expected files are usually not neighbours.
- **10 of 22 (45%) have a direct edge to at least one file that made the 34-item pool**, against a
  base rate of 3.4% for an arbitrary non-pool file. Controlling for degree by comparing each path
  only against non-pool files of *identical* degree, the expected count is 2.03 (Poisson-binomial,
  sd 1.24) versus 10 observed: **z = 6.4**. Restricting to degree strata with n >= 50 peers, where
  the base rate is actually estimable, it is 6 of 17 against 1.19 expected, z = 4.6.

So for nearly half the blind spot the graph channel has the answer within one hop of files it
already scored into the top 34 -- and still does not surface it.

**Two limits on this, stated because the conclusion is tempting.** First, "one hop from the pool"
is a proxy: `_propagate` starts from up to `seed_limit: 140` seed files, not from the final
34-item pool, so this does not prove the propagation could have reached them. Second, the
tiny-n strata are noise (three rows rest on 1-3 peers); the n >= 50 restriction above is the
number to trust.

**I must not repeat the comparison I nearly made here.** Finding 22's "expected paths are 96.3%
connected" cannot be set against the 5% co-expected adjacency above -- 17 cases at 5% and 83 at x
cannot average 96.3% -- which means the two numbers measure different things (component
reachability vs. a direct edge). Comparing them would have manufactured a dramatic contrast out
of a units mismatch.

**What this does and does not license.** It motivates the propagation mechanics -- level width
(task #16), and the missing `best_seen` guard -- as the next axis for roughly half of the 13.5 pp.
It says nothing about the other 12 paths, which have no edge into the pool at all and need a
different channel entirely.

---

## Finding 28 — the champion's pool-recall baseline was replayed from the WRONG report; two of my claims retracted

**The error.** `/tmp/replay-h17-ctrl.json`, which I used as the champion baseline for every
replay comparison in this series, records
`report: .code-diver/reports/protogen-h14-qwen35-4b-text-graph-100.json`. It is H14's probe
queries replayed through the H17 config, not the champion's own probes. `replay_pool_recall.py`
reads probe queries out of the report, so the source report is not a label -- it is half the
input.

**Two retractions.**

1. *"The replay is not deterministic at the pool boundary; the spread is about one expected
   path out of 163."* **False.** Three repeats on identical input returned byte-identical
   metrics: 0.859 / 0.820, 0.859 / 0.820, 0.859 / 0.820. I invented nondeterminism to explain
   a 0.006 gap that was a provenance mismatch. The tell was right there and I misread it: three
   of the five "lost" cases had **0** probes dropped, which under a real filter effect is
   impossible and under a different probe set is expected.
2. *The champion's pool recall is 0.865 / bundle 0.830.* **It is 0.859 / 0.820.** I quoted
   0.865 as the champion's number throughout.

**Everything re-scored against the correct baseline (0.859 / 0.820):**

| arm | pool_recall@34 | delta vs 0.859 |
|---|---|---|
| probe filter, `drop` (78 invented-path slots) | 0.871 | **+0.012** |
| frontier_limit 10 | 0.853 | -0.006 |
| frontier_limit 20 | 0.859 | 0.000 |
| frontier_limit 40 (default) | 0.859 | baseline |
| frontier_limit 80 | 0.859 | 0.000 |
| frontier_limit 160 | 0.853 | -0.006 |

The `drop` delta doubled (+0.006 -> +0.012) and is now deterministic rather than noise-suspect,
but the paired path-level split is 4 gained / 2 lost, exact binomial sign test **p = 0.688**.
Two net paths out of 163 cannot carry a conclusion; the direction is positive, the evidence is
not there. (The earlier 6-gained / 5-lost split was contaminated -- it compared two different
probe sets.)

**Task #16 closes anyway, more cleanly than before.** `frontier_limit` in {20, 40, 80} is
*exactly* identical, and both extremes cost one expected path. The level-width knob is flat
across an 8x range on this graph, against a deterministic baseline -- pre-registered |delta| <= 0.02
confirmed, and the axis is closed for real rather than within noise.

**Findings 25-27 were recomputed on the correct blind spot and all survive.** The corrected
blind spot is **23 paths in 18 cases** (was 22 in 17); 19 paths overlap, 4 are new
(`where-agent-factory`, `where-metrics-collector`, `where-pipeline-built`,
`where-session-cancel` -- exactly the cases whose "0 probes dropped" should have tipped me off),
3 are gone.

- Finding 26 (invented paths do not explain the blind spot): 9/18 blind cases carry an
  invented-path probe vs 42/82 fully-found = 50.0% vs 51.2%, two-proportion z = **-0.09**. No
  enrichment, unchanged conclusion.
- Finding 27 (half the blind spot sits one graph hop from the pool) gets *stronger*:
  **13/23 = 56.5%** adjacent to their case's 34-item pool, against an unmatched base rate of
  3.8% and a degree-matched expectation of **4.53 (sd 1.63), z = +5.18**. Restricted to degree
  strata with >= 50 peers, where the matched probability is not itself noise: **6/16 vs 1.45
  (sd 1.13), z = +4.03**. Both caveats from Finding 27 still stand.

**Process rule this earns.** Every replay comparison must assert that both arms name the same
source report before the numbers are read. The provenance is inside each output JSON; I had it
available the whole time and never looked until a 0.006 discrepancy forced me to. A comparison
whose two arms differ in an input I did not intend to vary is not a weak experiment, it is not
an experiment.

## Finding 29 — the invented-path probes are a latency defect, not a quality defect

Both arms of task #14, replayed against the corrected 0.859 / 0.820 baseline:

| arm | slots touched | pool_recall@34 | delta | paired | sign test |
|---|---|---|---|---|---|
| `drop` -- remove the whole probe | 78 dropped | 0.871 | +0.012 | 4 gained / 2 lost | p = 0.688 |
| `strip` -- remove only the invented token | 33 dropped, 45 rewritten | 0.865 | +0.006 | 2 gained / 1 lost | p = 1.000 |

`bundle_complete` is 0.820 in all three. Both arms point the same direction and neither is
significant; the whole effect is at most two paths out of 163.

**The prediction that failed, and what it tells us.** I pre-registered `strip` as the *more
precise* intervention: it removes the invented path while keeping the probe's ordinary query
words, so it should isolate "the fake path misleads retrieval" from "the probe's words were
needed". If the words were carrying value, `strip` should beat `drop`. It came in at half the
delta, and head-to-head `drop` -> `strip` is -0.006 (2 gained / 3 lost). So the surviving words
in those 45 probes are not contributing either -- a probe built around a hallucinated path is
apparently weak all the way through, not a good probe with one bad token.

**Where the value actually is.** 78% of path-hint slots are fabricated, they occur in 51% of
cases, and deleting them costs nothing measurable. On a system where 99.3% of wall-clock is LLM
inference, generating those slots and then retrieving on them is pure spend. That reframes the
axis from "fix a recall bug" to "delete work nobody uses" -- task #17, which needs a full eval
because it changes what the planner emits.

**What this does not say.** It does not say hallucinated paths are harmless in the answer -- the
guardrail here was pool recall, and `citation_fabricated_rate` was never in this measurement.

## Tooling — `scripts/compare_replay_arms.py`

Finding 28's process rule is now enforced in code rather than in this file. The script refuses
to compare two replay outputs whose `report` fields differ, unless `--allow-different-reports`
says the probe rewrite *is* the intervention; it also warns on differing `config` and on a
differing `candidate_limit` (which changes pool size and makes recall incomparable outright).
Verified against the actual mistake: pointing it at the mis-provenanced baseline raises, naming
both reports. It also folds in the paired path-level diff and the exact sign test, which I had
hand-written inline three times -- once with the wrong baseline.

## Pre-registration — task #15, rerank on Gemma-4 E2B (arm `protogen-h25-e2b-rerank`)

First arm to use the `llm_rerank.generation` override from task #12. One change from the
champion: rerank runs `gemma-4-e2b-it-4bit` on :8013, the answer still comes from
`Qwen3.5-4B-OptiQ-4bit` on :8012. Verified as a three-line diff; both stages resolve to the
intended model and the rerank stage inherits temperature 0.0 / timeout 240s.

**Why this is not just "E2B again".** Task #9 tried E2B as the *answer* model and it lost badly.
The bet here is that the two stages are not equally hard: ranking 34 short previews is closer to
a classification task than writing a cited explanation, so a 2B model may be adequate at the
stage that dominates *ingest* -- 34 previews x 850 chars is roughly 8k prompt tokens per case
against a ~700-800 tok/s prompt throughput.

**Predictions, in order of what would change my mind:**
1. `citation_expected_recall` non-inferior to the champion's 0.715 at |delta| <= 0.02. This is the
   claim; a drop past that kills the arm regardless of speed.
2. Mean wall-seconds per case drops 20-35%. If it drops less than 10%, the arm is pointless even
   at equal quality -- the whole reason to run a cheaper reranker is latency.
3. `citation_fabricated_rate` guardrail does not rise. Prior series showed fabrication tracks
   OptiQ quantization rather than model size, and E2B here is plain 4-bit, so I expect no rise
   -- if it rises anyway, that prior is wrong a third time.

Both 1 and 2 must hold for the arm to replace the champion. Quality-neutral-but-slower, or
faster-but-worse, both mean the axis closes.

## Finding 30 — Gemma-4 E4B-OptiQ as the answer model: 20% faster, and it fails both criteria

`protogen-h23-e4b-optiq`, one change from the champion (answer model
`Qwen3.5-4B-OptiQ-4bit` -> `gemma-4-e4b-it-OptiQ-4bit`), 100 cases, 0 errors, matched pairs:

| metric | champion | h23 E4B-OptiQ | delta | 95% CI |
|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.715 | 0.600 | **-0.115** | [-0.191, -0.039] |
| `citation_fabricated_rate` (guardrail) | 0.025 | 0.063 | **+0.039** | [0.006, 0.072] |
| `candidate_bundle_complete` (mechanism) | 0.670 | 0.650 | -0.020 | p = 0.81 |
| `candidate_file_recall` | 0.770 | 0.773 | +0.003 | [-0.058, 0.064] |
| mean duration | 66.7 s | 53.4 s | **-19.9%** | -- |

The CI on the primary excludes zero, so this is a real loss, not a null. The guardrail worsens
2.5x and its CI also excludes zero. The arm dies twice over; 20% latency does not buy 11.5 pp of
citation recall.

**The intervention was cleanly isolated, which is the useful part.** Retrieval is untouched --
`candidate_file_recall` 0.770 vs 0.773, bundle 0.670 vs 0.650, both null. The entire loss sits in
the answer stage, exactly where the one changed knob lives. So this is a clean statement about
the model, not a confounded one.

## Finding 31 — the latency/quality frontier, all eight completed 100-case arms

Ranked by the primary metric. This is the Pareto picture the goal asks for.

| arm | recall | fabricated | bundle | s/case |
|---|---|---|---|---|
| h22-qwen9b | **0.740** | 0.083 | 0.700 | 107.3 |
| **h17-ctrl-qwen35-4b (champion)** | 0.715 | **0.025** | 0.670 | 66.7 |
| h22-qwen4b-plain | 0.687 | 0.068 | 0.596 | 71.1 |
| h19-depth20 | 0.680 | 0.031 | 0.630 | **57.6** |
| h19-depth60 | 0.670 | 0.035 | 0.640 | 74.9 |
| h14-qwen35-4b-text-graph | 0.665 | 0.042 | 0.600 | 112.9 |
| h23-e4b-optiq | 0.600 | 0.063 | 0.650 | 53.4 |
| h20-e2b | 0.587 | 0.102 | 32.1 | 32.1 |

**Once the guardrail is applied the frontier collapses to two points.** Qwen9B is the only arm
that beats the champion on recall and it triples fabrication at 1.6x the latency. Everything
faster than the champion also fabricates more, except **h19-depth20: -3.5 pp recall for -13.6%
latency at 0.031 fabricated**. That is the only genuine speed/quality trade on the board, and it
is a retrieval-side change, not a model swap. Every model swap so far has been strictly worse.

**Fabrication is explained by neither size nor quantization alone, and I have said otherwise.**
The record:

- size: Qwen9B 0.083 vs Qwen3.5-4B-OptiQ 0.025 -- bigger fabricates *more*. Size refuted again.
- quantization, clean same-size comparison: Qwen 4B plain 0.068 vs Qwen3.5-4B-OptiQ 0.025. OptiQ
  cuts fabrication by two thirds.
- but across families at the same quantization: Qwen3.5-4B-OptiQ 0.025 vs Gemma E4B-OptiQ 0.063,
  a 2.5x gap with OptiQ held fixed.

So "the cause is OptiQ quantization" -- my summary of the earlier refutations -- is too strong.
OptiQ helps within a family at fixed size; it does not set the level. Model identity carries
independent weight. (The Gemma pair E2B-plain 0.102 vs E4B-OptiQ 0.063 confounds size with
quantization and cannot be used here.)

**A correction to my own pre-registration for task #15, made before the arm lands.** I justified
prediction 3 (fabrication will not rise with E2B on rerank) using the OptiQ prior, which
Finding 31 just weakened. The prediction still stands but for a sounder reason: fabricated
citations are produced by the stage that *writes* citations, and h25 leaves that stage as
Qwen3.5-4B-OptiQ. A reranker can only choose among real pooled paths, so it has no mechanism to
invent one. If fabrication rises materially in h25, something is wrong with my model of where
citations come from -- which would be a more interesting result than the arm itself.

## Finding 32 — the blind spot is a reranker CAPACITY ceiling, not a retrieval failure

A diagnostic replay at `candidate_limit 400` (`/tmp/replay-h17-ctrl-cl400.json`) reaches
**pool recall 0.988** -- 161 of 163 expected paths are retrievable. Where the 23 blind-spot paths
actually rank:

| rank band | paths |
|---|---|
| 31-60 | 7 |
| 61-100 | 7 |
| 101-200 | 5 |
| 201-400 | 2 |
| absent even at 400 | **2** |

Only two paths are genuinely unreachable (`where-authorization src/operators/models_config.py`,
`where-eval-judge src/eval/judge.py`). Fourteen sit between rank 31 and 100 -- just past the
34-item cutoff.

**The diagnostic is valid, and I checked before trusting it.** `query_limit` is derived from
`candidate_limit` in `replay_pool_recall.py:291`, so the deep run also retrieves deeper per probe
-- two things move together and that could have reordered everything. It did not: the two curves
are equal at the top, 0.859 vs 0.853 at k=34 and 0.908 vs 0.902 at k=60. Deeper probes add tail
without disturbing the head, so a rank read off the deep run is a fair estimate of where the path
sat all along.

**Now compose the two measured quantities:**

| candidate_limit | pool recall (replay) | rerank transfer (eval) | product |
|---|---|---|---|
| 20 | 0.791 | 0.966 | 0.764 |
| 34 | 0.859 | 0.890 | **0.765** |
| 60 | 0.908 | 0.831 | 0.755 |

**The product is pinned at 0.76 across a 3x range of candidate depth -- total spread 0.010.**
That is not a coincidence and it is not a plateau in the ordinary sense: the reranker's
degradation almost exactly cancels every path the deeper pool wins. The system is not
retrieval-limited. It is limited by how long a candidate list this reranker can rank without
losing precision. (The product is a composition of two separately-measured numbers and is an
estimate; the measured end-to-end at 34 is `citation_expected_recall` 0.715.)

**This retires three axes at once and explains why they were all flat.** `graph_weight` (task
#10), `frontier_limit` (task #16) and the probe filter (task #14) were all attempts to put better
candidates into a pool whose size was fixed -- and the transfer function then ate the difference.
Finding 27's "half the blind spot is one graph hop from the pool" is now fully explained: those
paths *are* propagated, they land at rank 35-100, and the cutoff drops them.

**Where the headroom is.** If pool coverage of 60 could be reranked at the transfer rate observed
for a 20-item list, the product would be 0.908 x 0.966 = **0.877 against 0.765 today, +11.2 pp**
-- larger than every intervention attempted in this series combined. Two ways to attack the
transfer function rather than the pool:

1. **Chunked rerank** -- rank 60 candidates as three lists of 20 (where transfer is 96.6%), then
   rerank the ~20 survivors. The rerank prompt is ingest-dominated, so 3x20 costs roughly the
   same prompt tokens as 1x60; the extra cost is two more round trips of short output.
2. **Cross-encoder rerank** -- `cross_encoder_rerank_retrieval_strategy.py` has existed in this
   repo the whole series and has never been run. It scores pairs without an LLM in the loop, so
   list length is not a precision constraint at all and 400 candidates is affordable.

Option 1 is the cheaper test and reuses the champion end to end. Option 2 is the bigger swing and
also attacks latency, since it removes an LLM call from the critical path of an ingest-bound
system.

**What would falsify the capacity story.** If chunked rerank at 3x20 does *not* beat single-shot
at 60, then list length was never the mechanism and the 89%/83% transfer rates are measuring
something else -- most likely that the reranker simply cannot tell these particular files apart,
which no amount of batching fixes.

## Finding 33 — correcting Finding 32: the "product pinned at 0.76" column was an identity in disguise

Finding 32 claimed the product of pool recall and rerank transfer is pinned at 0.76 across a 3x
range of `candidate_limit`, spread 0.010, and called that the signature of a capacity ceiling.
**Withdraw the number and the framing.** Two defects:

1. **The columns had mismatched provenance.** `transfer` was defined in the depth-sweep finding as
   `candidate_file_recall / pool_recall`, using the mis-provenanced pool recalls
   (0.761 / 0.865 / 0.896 -- see Finding 28). I then multiplied those ratios by the *corrected*
   pool recalls (0.791 / 0.859 / 0.908). Mixing a ratio's denominator from one run with a
   numerator from another is what produced the suspiciously tight 0.010 spread.
2. **With matched provenance the product is an identity.** `pool x (post / pool) = post`. It
   cannot be evidence of anything; it recovers the measured number by construction. This is the
   second tautology I have caught in this series and it has the same shape as the first -- a
   quantity that looks like a prediction but is algebraically forced.

**The corrected table. Post-rerank recall is measured directly, so no composition is needed:**

| candidate_limit | pool recall (corrected replay) | `candidate_file_recall` (measured) | transfer = post/pool |
|---|---|---|---|
| 20 | 0.791 | 0.735 | 0.929 |
| 34 | 0.859 | **0.770** | 0.896 |
| 60 | 0.908 | 0.745 | 0.820 |

**The conclusion of Finding 32 survives; only its arithmetic was decorative.** Pool recall rises
monotonically by 11.7 pp from depth 20 to 60. Post-rerank recall does not follow it: it peaks at
34 and then *falls*, an inverted U with spread 0.035 over the same range. Transfer declines
monotonically, 0.929 -> 0.896 -> 0.820. So the reranker, not retrieval, is what binds -- that
claim rests on the directly measured inverted U, which needs no product column at all.

**The headroom estimate, restated honestly.** If chunking let 60 candidates be ranked at the
transfer rate observed for 20-item lists, post-rerank recall would be 0.908 x 0.929 = **0.844
against 0.770 today, +7.4 pp** -- not the +11.2 pp I wrote, and on `candidate_file_recall`, not on
the primary `citation_expected_recall`. It is also a hypothetical that assumes chunking fully
recovers the short-list transfer rate, which is the very thing task #18 is meant to test rather
than assume.

**Attribution requirement for task #18, which I nearly missed.** The chunked arm changes two
things against the champion: `candidate_limit` 34 -> 60 *and* chunking. There is no single-shot
eval arm at `candidate_limit: 60` in this series -- the 0.745 above comes from the depth sweep, a
different config family. So a win by the chunked arm would not be attributable to chunking on its
own. Either run single-shot-at-60 as a second arm, or state the ambiguity in the result instead of
claiming chunking caused it.

---

## Finding 34 -- **RETRACTED IN FULL.** See Finding 35.

> Everything below this line is wrong and is kept only so the mistake stays on the record. h25
> never reranked with E2B: `llm_rerank.generation` was ignored by `cmd_evaluate_answers`, so every
> one of its reranks ran on Qwen3.5-4B-OptiQ, the champion's own model. The arm was an unwitting
> replicate. On top of that I compared its 54-case prefix against the champion's 100-case mean,
> which is not a comparison at all. Both defects pushed in the same direction, which is why the
> numbers looked like a coherent story.

h25 (`protogen-h25-e2b-rerank`) is the champion with one change: the *rerank* stage moves to
`gemma-4-e2b-it-4bit` on a second `mlx_lm` server (:8013), answer generation untouched on :8012.
At 54/100 cases all three pre-registered predictions have resolved, and two of them failed:

| metric | champion (h17-ctrl) | h25 @54 | pre-registered bound | verdict |
|---|---|---|---|---|
| `citation_expected_recall` | 0.715 | 0.685 | non-inferior at abs(d) <= 0.02 | **FAIL** (-0.030) |
| s/case (excl. cold) | 66.7 | 63.1 | 20-35% faster | **FAIL** (-5.4%) |
| `citation_fabricated_rate` | 0.025 | 0.028 | <= 0.035 | pass |
| `candidate_file_recall` | 0.770 | 0.732 | (mechanism, not pre-bounded) | -0.038 |

**Why the latency prediction failed is the useful part.** A 2B reranker is ~2x smaller than the 4B
and still returns only ~5% of the stage's wall-clock. That is exactly what an ingest-bound system
predicts: the rerank prompt is ~16 kB of repository context plus 34 previews at 850 chars, so the
cost is dominated by prompt *tokens*, and prompt-processing throughput does not scale with the
inverse of parameter count anywhere near 1:1. Shrinking the generative reranker is the wrong lever.

**This strengthens the case for task #19 rather than weakening it.** A cross-encoder does not read
a list at all: it scores 34 independent (query, document) pairs, each a few hundred tokens, with
zero generated output and no repository-context preamble. The saving comes from deleting the long
prompt, not from a smaller model reading it faster. h25 is the control that shows the difference
matters -- without it, a cross-encoder win would be confoundable with "smaller rerank model".

Interim, not final: 46 cases outstanding. The deltas above are directional and the primary is
already outside its bound, but the final numbers go in the frontier table, not these.

## Task #19 wiring landed, CPU-only, and its pre-registration

`RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER` + factory branch + `_graph_file_strategy` helper
(the graph_file construction was duplicated twice) + `configs/context-awareness/protogen-h28-cross-encoder.yml`.
982 unit tests pass, 3 new.

**Why a new strategy id was necessary and not gold-plating.** The pre-existing
`CROSS_ENCODER_RERANK` wraps `HybridRetrievalStrategy`, not `GraphFileRetrievalStrategy`. Running
the champion against it would have swapped the rerank primitive *and* deleted the entire graph
layer in one arm, leaving neither change attributable -- the same attribution trap Finding 33
flagged for task #18. The new id makes h28 a one-line diff from the champion.

**Correction to what I told the user earlier: the cross-encoder is not unused.** It ran in June
2026 (`docs/qwen3-cross-encoder-rerank-2026-06-02.md`) and ships in three config families with
existing reports. It has never run in *this* h-series. And the June doc's claim that "a dedicated
reranker is a better ranking primitive than a small generative model forced to emit JSON" is
interpretation, not measurement: that table has no LLM-rerank arm, so it compares cross-encoder
against *no* reranking. h28 is the first arm in the project that actually tests that sentence.

**Pre-registered for h28, before the server is even started:**

- Primary `citation_expected_recall`, non-inferior at abs(d) <= 0.02 against 0.715.
- Guardrail `citation_fabricated_rate` <= 0.035 (champion 0.025).
- Mechanism `candidate_file_recall` against 0.770 -- the axis Finding 33 identifies as
  reranker-capped, so this is where a better primitive should show up if it is better.
- What is being bought: s/case. Predict 48-56 against 66.7, since the stage being replaced is
  17.5 s and the June measurement for the cross-encoder was ~2.2 s.
- **Named failure mode, declared in advance.** Qwen3-Reranker was trained on prose and code
  passages. This index stores *file-level metadata* -- summaries and API manifests, not bodies
  (the deliberate lean-index design). A 0.6B cross-encoder may simply be out of distribution on
  that text. If the primary drops hard, the 4B GGUF is already on disk and must be run before any
  conclusion is drawn about cross-encoders as a class.

---

## Finding 35 -- the rerank-model override never reached this eval path, and the accident handed me a noise floor

**The defect.** `llm_rerank.generation` was honoured in exactly one place:
`RetrievalStrategyFactory._rerank_generation_config`, which feeds the *strategy* wrapper
`LlmRerankRetrievalStrategy`. But in `cmd_evaluate_answers` -- the command every arm in this
series runs -- that wrapper is never invoked:

- `probe_strategy = self.query_retrieval_strategy or self.retrieval_strategy`
  (`answer_evaluator.py:337`), and `--agentic-query-search-strategy graph_file` sets
  `query_retrieval_strategy`. So the object built from `config.search.strategy` is constructed and
  then never used.
- The single final rerank is `AnswerCandidateReranker(answer_provider, config.llm_rerank)`
  (`cli.py:2833`) -- a *separate* class that shares the prompt builder and parser but not the
  provider resolution. It took the answer provider unconditionally.

**Proof, not inference.** Every `final_rerank.model` in the h25 partial reads
`mlx-community/Qwen3.5-4B-OptiQ-4bit`, 58 of 58 cases, mean 16.8 s. The `:8013` E2B server ran the
whole time and served nothing.

**Two consequences for the record.** Task #12 ("decouple the rerank model from the generation
model") was marked complete on the strength of the strategy-side wiring and unit tests; it never
reached the code path the experiments use. Task #15 was therefore never tested at all and goes
back to pending.

**And the same trap was about to eat task #19.** `search.strategy: graph_file_cross_encoder` is
read from the same ignored field. h28 as first written would have produced numbers identical to
the champion and I would have reported "the cross-encoder is a wash" -- a false null with a
plausible mechanism attached. I caught it only because reading the CLI for #17 put
`AnswerCandidateReranker(answer_provider, ...)` in front of me. The h28 runner was already queued
and waiting on h25's pid; it has been killed and relaunched against the fixed wiring.

**The fix, three parts:**

1. `config/rerank_generation_config.py` -- one shared resolver for `llm_rerank.generation`. The
   strategy factory's private method now delegates to it. Two call sites, one definition; that is
   what failed here.
2. `answering/answer_candidate_reranker_factory.py` -- maps `config.search.strategy` to the final
   candidate reranker (`CROSS_ENCODER_RERANK` and `GRAPH_FILE_CROSS_ENCODER` -> cross-encoder,
   everything else -> generative) and resolves the generation override. `cli.py` calls it instead
   of constructing `AnswerCandidateReranker` directly.
3. `answering/answer_candidate_cross_encoder_reranker.py` -- duck-type-identical to
   `AnswerCandidateReranker` (`candidate_limit`, `rerank(query, candidates, limit) ->
   (results, payload)`) and emits the same payload keys, because the report schema, the metrics,
   and every script in `scripts/` read those keys. Token and cost fields stay 0: a cross-encoder
   emits no tokens and a fabricated count would corrupt the cost-per-case series.

Verified: the champion still resolves to `AnswerCandidateReranker` with the answer provider
reused by identity (no second client, no behaviour change), h28 to the cross-encoder at
`Qwen3-Reranker-0.6B`, h25 to E2B. 994 unit tests pass, 12 new.

### The unintended replicate is the most useful thing in this finding

Because h25 differs from the champion only in an ignored field, it is a **same-config re-run** --
the first one in this series. It has since completed all 100 cases (all 100 `final_rerank.model`
entries read `Qwen3.5-4B-OptiQ`, so the replicate interpretation is confirmed at full n). Paired,
case by case, 100 against 100:

| metric | champion | replicate | delta | paired 95% CI on delta |
|---|---|---|---|---|
| `citation_expected_recall` | 0.7150 | 0.7100 | -0.0050 | **[-0.043, +0.033]** |
| `citation_fabricated_rate` | 0.0245 | 0.0215 | -0.0030 | [-0.014, +0.008] |
| `candidate_file_recall` | 0.7700 | 0.7650 | -0.0050 | [-0.031, +0.021] |
| `candidate_bundle_complete` | 0.6700 | 0.6700 | +0.0000 | [-0.039, +0.039] |
| `answer_grounded` | 0.8200 | 0.8400 | +0.0200 | [-0.028, +0.068] |
| s/case | 66.7 | 62.2 | **-6.7%** | **[-8.3%, -5.1%]** |

91 of 100 cases agree exactly on the primary; 9 differ from `mlx_lm` nondeterminism alone, and a
single case swings the mean by up to 0.01 (per-case diffs are +/-0.5 and +/-1.0). Two things follow,
and both cut against me:

- **The resolvable difference is the CI half-width, not the observed delta.** The point estimate
  came in at a reassuring -0.005, but sd(diff) is 0.195, so the paired SE is 0.0195 and a
  single-run comparison cannot resolve anything smaller than about **+/-0.04 on the primary**. My
  pre-registered non-inferiority bound of |d| <= 0.02 is *inside* that -- it cannot be tested by
  one run per arm. It stands for arms already declared under it, but only ever as
  "indistinguishable", never "shown equivalent".
- **The latency CI excludes zero.** Two runs of identical config differ by -6.7% [-8.3%, -5.1%].
  That is not zero-mean noise; it is a systematic between-run shift. See Finding 37 -- it turns out
  to be uniform across stages, which is what makes it fixable.

*(Corrects an interim version of this table computed on the first 58 cases, which reported deltas
of -0.017 and -8.2% and which I wrongly described as the noise floor. Those were one prefix's point
estimates, not a spread; the spread is the CI column above.)*

The champion's 100-case figures (0.715 / 0.025 / 0.770 / 66.7) remain the reference point, but
they are now known to be one draw from a distribution with this much spread, not a fixed value.

**Also fixed while queueing h28:** the runner's "port already has a listener, reusing it" branch.
`:8080`, the port the June notes use, is held on this machine by an unrelated `jbcc-api` process.
Reusing a stranger's port means the smoke test gets a plausible-looking answer from the wrong
service. The runner now refuses an occupied port and h28 uses `:8081`.

## Finding 36 -- the noise floor retires two of the three pending arms, and it is a methodology change

Finding 35's replicate makes an uncomfortable point explicit: **most of this series has been
chasing effects smaller than the harness can resolve in one run.** With +/-0.017 on the primary and
+/-8% on s/case between two runs of identical config, a single 100-case arm can only settle
interventions predicted to move more than that.

Sorting the pending arms against it:

| arm | predicted effect | resolvable in one 100-case run? |
|---|---|---|
| #19 cross-encoder | s/case -25%, primary unknown and possibly large either way | **yes** |
| #18 chunked rerank | +7.4 pp on `candidate_file_recall` (hypothetical ceiling) | **yes**, once it is not a no-op |
| #17 drop path hints | primary ~0 (Finding 14: +0.012, p=0.688), s/case saving unquantified | **no** |
| #15 E2B rerank | s/case < 8% by Finding 35's own reasoning | **no** |

So #17 and #15 should not consume ~1.8 h of GPU each to produce a number indistinguishable from a
re-run of the champion. They are not dead -- they need a design that can see them:

- **Deterministic replay is the right instrument for small effects.** The probe-query replay is
  ~0.6-0.7 s/case and its repeats came back byte-identical three times; that is precisely because
  it stops before the nondeterministic LLM stages. Effects of 0.01 are visible there and invisible
  in a full eval. #17 already has a replay result (+0.012, null); a full eval cannot improve on it.
- **A full eval can only settle a small effect with replication**, i.e. n runs per arm and a paired
  test across matched cases, which multiplies the GPU cost by n. Not worth it for either arm.

**Re-measured #17's premise with correct provenance while deciding this** (champion 100-case
report, path-like tokens in planner probes excluding the verbatim question): **123 tokens, 90 of
them absent from the repository = 73.2%, touching 62 of 100 cases.** My earlier figures were 78%
and 51%; different extraction, same conclusion. The phenomenon is real and large. What is not
established is that removing it buys anything measurable -- and Finding 14 already tested that and
came back null.

**Rule going forward:** a full 100-case eval requires a pre-registered predicted effect above the
noise floor (>0.03 on the primary, or >15% on s/case). Anything smaller goes through replay, or
gets replicated, or does not get run.

## Finding 37 -- the between-run latency shift is a uniform machine-state factor, so use stage *share*, not seconds

The replicate ran 6.7% faster with byte-identical prompts and models. Broken down by stage, paired
over 100 cases:

| stage | champion s | replicate s | delta | paired 95% CI | pct |
|---|---|---|---|---|---|
| query plan | 9.33 | 8.71 | -0.62 | [-0.73, -0.51] | **-6.6%** |
| final rerank | 17.51 | 16.62 | -0.90 | [-1.15, -0.64] | **-5.1%** |
| residual (answer + retrieval) | 39.82 | 36.86 | -2.96 | [-3.87, -2.05] | **-7.4%** |
| total | 66.66 | 62.19 | -4.47 | [-5.55, -3.39] | **-6.7%** |

Every stage moved by roughly the same proportion. Nothing about the workload changed, so this is
**machine state -- thermal/DVFS, or contention during the champion run -- applied multiplicatively
to every LLM call.** It is not attributable to anything a config can express.

**This is a direct threat to the stated project goal.** A latency/quality Pareto frontier assembled
from one run per arm carries a shared multiplicative factor of order +/-7% on the latency axis, of
unknown sign per arm. Arms separated by less than that on s/case cannot be ordered, and I have been
ordering them.

**The fix falls out of the uniformity.** A multiplicative factor cancels in a ratio:

| | champion | replicate |
|---|---|---|
| rerank share of total | 26.3% | 26.7% |

The *share* is stable to 0.4 pp across runs whose absolute totals differ by 4.5 s. So:

- **Report stage latency as a share of total.** For h28 the pre-registration becomes falsifiable
  despite the drift: the final-rerank share should fall from ~26% to the low single digits if a
  cross-encoder replaces a 17 s generative call. That prediction cannot be faked by a fast machine
  day.
- **Quote absolute s/case only against a same-session control**, or as a range, never as a single
  number compared to an arm run hours earlier.
- Supersedes Finding 36's "> 15% on s/case" rule, which was set against a noise floor I had
  mis-estimated: the real rule is *ratios are comparable across runs, absolute seconds are not*.

Note also that the replicate held a second model server resident on `:8013` the whole time
(gemma-4-e2b, serving nothing) and still ran faster. Memory pressure from an idle resident model is
not what is driving the 7%.

### h28 smoke test, recorded before the arm's results exist

`llama-server` with the 0.6B GGUF on `:8081`, 34 documents, the real list depth:
**0.81 s, 10 scores returned.** For comparison the generative stage it replaces is 17.5 s. The
June figure of ~2.2 s was the 4B; this is the 0.6B.

Sharpening the pre-registration accordingly, and recording it now rather than after the fact:

- **Rerank share of total should fall from 26.3% to roughly 1-2%.** This is the drift-immune
  prediction from Finding 37.
- **Absolute s/case should land near 50** (66.7 - 17.5 + 0.8 = 50.0 at champion machine speed,
  ~46.6 at the replicate's speed). The pre-registered 48-56 window covers both, but per Finding 37
  the share is the claim that counts and the seconds are the illustration.
- Primary and guardrail bounds are unchanged, and per Finding 35 a primary difference smaller than
  about +/-0.04 will not be resolvable from this single run -- which must be stated in the result,
  not discovered afterwards.

### Finding 37 is now enforced by the comparison tool, not by my discipline

`scripts/compare_arm_runs.py` printed one unpaired `duration_ms` mean and nothing else. Every
stage-level latency claim in this session -- including the Finding 37 numbers themselves -- was
computed by ad-hoc Python in a throwaway shell, which is exactly how Finding 34 got onto the
record. The script now prints a paired stage table:

```
  stage        baseline s    arm s   delta s   95% CI (delta)   share baseline   share arm
    plan / search / rerank / generation / other / total
```

Design points worth keeping:

- **The five named stages partition `total` exactly**, so the share column sums to 1.0 and no time
  can hide in a gap. `search` is `retrieval - plan - rerank` (retrieval brackets the other two),
  clamped at zero with the remainder falling into `other`; a unit test asserts the partition holds
  even when the clamp fires.
- **Shares are printed alongside seconds, with the reason in the output itself.** A test asserts
  the property the verdict rests on: scale every stage of a run by 1.30 and the shares are
  unchanged while the total's delta CI excludes zero.
- Old reports lacking the `metrics` duration keys fall back to the `query_plan` payload those keys
  were copied from, so the tool works across the whole report series.

Re-deriving Finding 37 through the tool reproduces it (champion vs the h25 replicate, n=100):

| stage | champion s | replicate s | delta CI | share champion | share replicate |
|---|---|---|---|---|---|
| plan | 9.33 | 8.71 | [-0.73, -0.51] | 14.0% | 14.0% |
| search | 1.08 | 1.04 | [-0.42, +0.34] | 1.6% | 1.7% |
| rerank | 17.51 | 16.62 | [-1.15, -0.64] | 26.3% | 26.7% |
| generation | 38.74 | 35.81 | [-3.71, -2.14] | 58.1% | 57.6% |
| total | 66.66 | 62.19 | [-5.55, -3.39] | 100% | 100% |

Three of four stages moved by an amount whose CI excludes zero, and the shares moved by at most
0.5pp. **That 0.5pp is the noise floor for a share comparison** -- the first one this series has.
It is what makes the h28 prediction sharp: 26.3% -> low single digits is 50x that floor.

### h28 in flight, at n=8

Recording the running numbers before the arm finishes so the final report cannot be read as
post-hoc: total 51.5 s/case, plan 8.66 s, **rerank 1.78 s = 3.4% share**, generation 37.4 s = 72.6%,
primary 0.714 (champion 0.715), 0 errors, `final_rerank.model` reads `Qwen3-Reranker-0.6B` via
`llama_cpp` on every case.

**The 3.4% is above my pre-registered "roughly 1-2%".** The smoke test measured 0.81 s for one
34-document call; in the eval the stage costs 1.78 s. The gap is not mysterious -- the smoke test
timed the HTTP call alone -- but the prediction was stated against the smoke number and it was
optimistic. The direction and the order of magnitude hold; the point estimate was wrong by ~2x.

### Task #18 (chunked rerank): the extraction, designed but deliberately not written yet

Confirmed by reading both files. `LlmRerankRetrievalStrategy` owns the chunk reduction
(`_chunking_applies` / `_chunk_survivors` / `_chunk_keep`, lines 53-88) and it is reachable only
through `search()`, which `cmd_evaluate_answers` never calls. `AnswerCandidateReranker.rerank()`
does one call and has no seam to chunk at: the provider call and the payload construction are fused
into a single try block.

The extraction that makes the arm possible:

- New `ChunkedCandidateReduction(chunk_size, chunk_keep)` with `applies(count)` and
  `reduce(candidates, rank_chunk)`, where `rank_chunk(chunk, keep) -> list[SearchResult]`. The two
  owners pass their own closure; the reduction owns only the slicing, the trailing-chunk skip
  (`len(chunk) <= keep` has nothing to select), and the `max(1, ...)` keep floor.
- `AnswerCandidateReranker` needs `_ranked_once(...) -> (results, call_payload)` split out of
  `rerank()` before it can supply that closure.
- **Payload contract, decided in advance:** keep every existing key and make `duration_ms` and the
  three token counts *sums across all K+1 calls* -- that is already the honest reading of "what the
  rerank stage cost" -- and add `chunk_calls` and `chunk_candidate_count` alongside. Every
  `scripts/` consumer reads the existing keys and keeps working; the new keys are what makes the
  reduction visible. Note this makes the stage-share table above directly interpretable for the
  arm: chunking trades share for pool depth.
- **The champion must stay byte-identical**: `chunk_size is None` has to short-circuit before any
  new code path, exactly as the strategy already does.

**Not written yet, and the reason is h28, not caution about the refactor.** If a 0.6B cross-encoder
is non-inferior at 34 candidates, the interesting deep-pool arm is a cross-encoder at 60 in a single
shot -- 60 documents at the measured rate is well under 3 s, so there is nothing to chunk and the
whole reduction is moot for the configuration we would actually ship. Chunking only earns its
complexity if the generative reranker stays in the champion. Sequencing this after h28 avoids
building a mechanism for a stage we may be about to delete.

Attribution requirement from the original plan still stands either way: no single-shot eval at 60
candidates exists in this config family, so a chunked-60 arm needs a single-shot-60 control or its
delta is unattributable between "more pool" and "chunked ranking".

### h28 provenance check, run before the results (not after)

Loaded both configs through `ConfigLoader` and diffed the resolved objects rather than the YAML,
so defaults and overrides are compared as the code will actually see them:

| | champion (h17-ctrl) | h28 |
|---|---|---|
| graph artifact | `.code-diver/protogen-h17-ctrl.json` | same |
| `graph_file_search` (all 15 knobs) | seed 140 / lex 280 / weights .25/.25/.2/.1/.45 / depth 2 / neighbor 40 / decay .65 | identical |
| embedding model | Qwen3-Embedding-0.6B-4bit-DWQ | same |
| generation model | Qwen3.5-4B-OptiQ-4bit | same |
| `search.strategy` | `graph_file_rerank` | `graph_file_cross_encoder` |
| final rerank pool | `llm_rerank.candidate_limit` 34 | `cross_encoder_rerank.candidate_limit` 34 |

**Single-knob diff, and the pool depth matches at 34** -- so a primary difference is attributable to
the ranking primitive and not to how much it had to rank. The champion config also carries a
`cross_encoder_rerank` block (limit 40, `:8080`) that has always been inert there; it stays inert
because `search.strategy` is what selects the primitive. Worth noting that `:8080` in that stale
block is the port an unrelated `jbcc-api` listener holds -- another reason the h28 arm was moved to
`:8081` and the runner made to refuse an occupied port rather than reuse it.

## Finding 38 -- h28 (cross-encoder final rerank): latency win, guardrail failure

100/100 cases, 0 errors, 0 rerank fallbacks. Every case's `final_rerank` reads
`Qwen3-Reranker-0.6B` via `llama_cpp`, so the arm actually ran the thing it claims to (the check
Finding 35 taught us to make first, not last).

### Verdict against the pre-registration

| claim | pre-registered | actual | outcome |
|---|---|---|---|
| primary `citation_expected_recall` | non-inferior, abs delta <= 0.02 | 0.715 -> 0.760, **+0.045 [-0.014, +0.104]** | non-inferiority met; **superiority NOT shown** -- CI includes zero |
| guardrail `citation_fabricated_rate` | <= 0.035 | 0.025 -> **0.053**, +0.028 **[+0.004, +0.053]** | **FAILED**, and the CI excludes zero |
| mechanism `candidate_file_recall` | vs 0.770 | 0.805, +0.035 [-0.023, +0.093] | improved, not resolvable |
| rerank share of total | "roughly 1-2%" | **4.0%** (26.3% -> 4.0%) | direction right, **point estimate wrong by 2-4x** |
| absolute s/case | 48-56 | **45.9** | below the window -- faster than predicted |

Stage table (n=100, paired):

| stage | champion s | h28 s | delta CI | share ch. | share h28 |
|---|---|---|---|---|---|
| plan | 9.33 | 8.40 | [-1.05, -0.80] | 14.0% | 18.3% |
| search | 1.08 | 1.65 | [+0.30, +0.85] | 1.6% | 3.6% |
| rerank | 17.51 | **1.85** | [-16.05, -15.29] | 26.3% | **4.0%** |
| generation | 38.74 | 33.97 | [-6.04, -3.50] | 58.1% | 74.0% |
| total | 66.66 | **45.88** | [-22.25, -19.32] | 100% | 100% |

The share floor established above is 0.5pp. A 22.3pp move on the rerank share is ~45x that floor:
**the latency result is the one unambiguous outcome of this arm.** A 9.5x cheaper rerank stage, and
the pipeline is now generation-dominated at 74%.

### Why the guardrail broke, and why it is not a retrieval failure

Fabricated = a cited path that appears in no context file the model was shown. Cases with at least
one: **8 -> 18**. Total out-of-bundle citations 10 -> 25. They are not invented strings; they are
real repo paths the model was not given -- `src/ailoop/README.md`, `src/app.py`,
`src/api/routes/sessions.py`, `prompts.examples/*.md`.

On the 15 cases where fabrication got worse:

- `candidate_file_recall` delta is **exactly 0.000** -- retrieval brought back the same files.
- h28 cited **5.13 paths/case vs 4.20**.
- the primary improved **+0.100** there, against +0.035 on the other 85.

So the reranker did not retrieve worse; it **reordered the bundle**, which changed the prompt, which
made the model cite more aggressively -- and citing more raises the primary and the fabrication rate
together. `answer_grounded` (0.820 -> 0.730) is largely downstream of this by construction: it
requires `not fabricated`.

### Decision

**h28 does not promote.** The guardrail was pre-registered as binding "regardless of the primary
result" and it failed with a CI that excludes zero; the primary gain that came with it is not
resolvable at n=100. Reversing that on the strength of a +0.045 point estimate would be exactly the
post-hoc rule change this series exists to avoid.

But the failure is diagnosed, and it is not in the reranker. Two follow-ups, in order:

1. **Keep the cross-encoder, fix citation discipline.** The 22pp latency reclaim is real and the
   defect is a generation-side one. If constraining the answer prompt to cite only shown files
   brings fabrication back under 0.035, the arm is re-run and judged on the same pre-registration.
2. **Only then revisit pool depth.** At 1.85 s the rerank stage can afford 60 candidates in one shot
   (~3 s), which makes the task #18 chunking mechanism unnecessary -- as anticipated above.

### Process error, recorded

`src/code_diver/cli.py` was modified at 22:37:46; the h28 process started at ~22:35. Python imports
once, so the run was unaffected and its results stand -- but the `final_rerank_*` settings stamp
added by that edit **is absent from this report**. The guard against Finding 35 is therefore not
demonstrated on the very arm that motivated it; provenance here rests on the per-case
`final_rerank.model` field instead, which is sufficient but was not the plan. Do not edit source
during a run, even when the edit is provably safe for the running process.

## h29: the citation allowlist -- design and pre-registration

### The change

`evaluation.restrict_citations_to_context` (default **false**, so every run before this one stays
reproducible). When on, `AnswerEvaluator._answer_prompt` appends the citable set to the prompt:

```
Citable files -- every citation path must be copied exactly from this list:
  - src/agents/base/factory.py
  - ...
Citing any other path is an error, even one you believe exists in this repository. If the
answer needs a file that is not listed, say so in the answer instead of citing it.
```

Three design points, each with a reason:

- **The list is `context.files`, the exact set `AnswerGroundingMetrics.score` grades against.** A
  test asserts this. Telling the model one boundary and scoring it on another would be its own bug.
- **The escape hatch is deliberate.** Without "say so instead of citing it" the model is pushed to
  substitute a listed file it does not believe in -- trading a fabricated citation for a wrong one,
  which the guardrail would score as an improvement.
- **An empty bundle gets no allowlist at all.** An empty list reads as "cite nothing"; a case where
  retrieval returned nothing should still explain what is missing.

The flag is written into the report settings block, so an h29 report cannot be mistaken for an h28
one -- the discipline the missing `final_rerank_*` stamp failed to demonstrate on h28 itself.

### Why two runs and not one

The champion's 0.715 primary was measured without the allowlist. If the allowlist depresses the
primary generally, comparing h29-arm against that number credits the reranker for a prompt effect.
So the pair is **h29-ctrl** (champion + allowlist) and **h29-arm** (cross-encoder + allowlist), each
one knob from its own predecessor. ~111 min and ~76 min, sequential, one GPU job at a time.

### Screening pilot first, pre-registered before it runs

Before spending 3.2 hours: run h29-arm on **only the 18 cases where h28 fabricated**
(`/tmp/protogen-h28-fabricating-18.jsonl`), ~14 min.

**This is a screen, not evidence.** Those 18 were selected *because* they fabricated, so regression
to the mean will improve them even if the change does nothing -- the replicate showed ~9% of cases
flip run-to-run on their own. Stating the gate in advance so the screen cannot be read as a result:

- **Proceed to the full pair only if cases-with-any-fabrication drops from 18/18 to <= 4/18.**
  A no-op would be expected to move ~2, so 4 is a deliberately generous floor that still separates
  "the prompt works" from "the sampler wandered".
- **Watch the primary on those 18.** If the allowlist makes the model cite less rather than cite
  better, `citation_expected_recall` will fall here first. A collapse means redesign, not proceed --
  even if fabrication hits zero, which it trivially would if the model stopped citing.
- Whatever the screen shows, the promotion decision comes from the full 100-case pair, and the
  guardrail bound stays 0.035 with the primary judged non-inferior against **h29-ctrl**, not h17.

### h29 screening pilot: passed, exactly at the pre-registered bound

18 cases, 0 errors, `restrict_citations_to_context: true` present in the report settings block --
the provenance stamp that h28 was missing now works.

| | h28 (these 18) | pilot |
|---|---|---|
| cases with any fabrication | 18 | **4** (gate was <= 4) |
| mean `citation_fabricated_rate` | 0.293 | 0.065 |
| mean `citation_expected_recall` | 0.750 | 0.722 |
| mean citations/case | 5.22 | 5.06 |
| mean s/case | 47.1 | 45.7 |

**It cleared the gate by nothing at all -- 4 against a bound of 4.** Recording that rather than
rounding it into a success: the screen says "proceed", not "solved".

The primary held (-0.028 on hard-selected cases, one case 1.00 -> 0.50), and the model did not stop
citing -- 5.06 vs 5.22 per case, with several cases citing *more* and fabricating nothing
(`where-infra-agent` went 4 -> 8 citations, 0.25 -> 0.00 fabrication). So the allowlist redirected
citations rather than suppressing them, which was the failure mode the escape-hatch clause was
written to avoid.

#### The 4 residuals are two different defects, and only one is what we thought

Checking every off-list path against the actual repo (`../protogen`):

1. **Real files the model was not shown** -- `src/app.py` (bundle had `specs/src/app.py`),
   `specs/21_feature_driven_pipeline.md`, `specs/06_pipeline.md`. All exist. The allowlist
   instruction was simply not obeyed. 2 cases.
2. **Path transcription** -- `prompts/examples/api.md`, `prompts/examples/CLAUDE.md`,
   `prompts/examples/TEMPLATE.md`, `prompts/examples/frontend.md`. **None of these exist.**
   `prompts.examples/api.md` does -- with a dot, not a slash. The model is normalising an unusual
   directory name into the conventional one. 2 cases.

Mode 2 could be "fixed" by snapping a cited path to a unique separator-normalised match in the
allowlist. **Not doing that.** A path that does not exist is unusable to a developer whatever
caused it, so scoring it as fabricated is correct -- and relaxing a guardrail after seeing which way
it fails is the exact post-hoc move this series exists to prevent. It stays a known residual.

### h29 full pair, pre-registered before launch

Both at 100 cases, sequential (one GPU job at a time), arm first because it is the one that decides
whether the latency win survives.

**h29-arm** (`graph_file_cross_encoder` + allowlist), vs h28 and vs h29-ctrl:

- guardrail `citation_fabricated_rate` <= 0.035; **predicted 0.012-0.020**. Projection: the 82 cases
  that fabricated nothing in h28 stay near zero and the 18 land at the pilot's 0.065, giving ~0.012.
  The allowlist changes the prompt for all 100 though, so the 82 can move either way -- that is
  precisely what this run measures and the pilot cannot.
- primary non-inferior against **h29-ctrl**, not against h17. Per Finding 35 nothing under ~+/-0.04
  is resolvable at n=100, so a "non-inferior" verdict here means indistinguishable, and I will say
  so rather than discover it afterwards.
- primary vs h28's 0.760: **predicted 0.72-0.76** (the pilot lost 0.028 on hard-selected cases).
- rerank share ~4%, s/case ~46 -- the allowlist adds prompt tokens, so a small generation increase
  is expected and would not be a finding.

**h29-ctrl** (champion + allowlist), vs h17-ctrl:

- primary vs 0.715: **predicted roughly unchanged**, since the champion fabricated on only 8 cases.
- `citation_fabricated_rate` vs 0.025: **predicted 0.005-0.015**.
- If the ctrl's primary drops materially while the arm's holds, the allowlist interacts with the
  reranker and neither run alone is interpretable -- state that rather than picking the flattering
  comparison.

## Finding 39 -- h29: the cross-encoder survives the guardrail, and the primary moves for the first time

Both runs 100/100, 0 errors, `restrict_citations_to_context: true` stamped in both settings blocks,
`final_rerank.model` correct on every case of both.

### The four comparisons, all paired at n=100

| comparison | primary | guardrail `citation_fabricated_rate` |
|---|---|---|
| **allowlist alone**: h17-ctrl -> h29-ctrl | 0.715 -> 0.695, -0.020 [-0.054, +0.014] | 0.025 -> 0.015, -0.010 [-0.025, +0.006] |
| **allowlist on the arm**: h28 -> h29-arm | 0.760 -> 0.770, +0.010 [-0.021, +0.041] | 0.053 -> **0.031**, -0.022 [-0.047, +0.004] |
| **decisive (matched prompt)**: h29-ctrl -> h29-arm | 0.695 -> 0.770, **+0.075 [+0.012, +0.138]** | 0.015 -> 0.031, +0.016 [-0.006, +0.039] |
| **vs the incumbent**: h17-ctrl -> h29-arm | 0.715 -> 0.770, +0.055 [-0.009, +0.119] | 0.025 -> 0.031, +0.007 [-0.016, +0.030] |

**The decisive comparison is the first resolvable primary gain in this series** -- +0.075 with a CI
that excludes zero, against a floor of ~+/-0.04 established by the replicate.

**And the caveat that goes with it, stated rather than buried:** h29-ctrl's own primary landed 0.020
below h17-ctrl's, which is itself unresolvable noise. If the control's true value is 0.715 rather
than 0.695, the arm's gain is +0.055 with a CI that includes zero. Two of the three control
comparisons overlap zero. The point estimate is positive in all three, the significance in one is
partly bought by the control landing low. **Read this as "probably better, demonstrated non-inferior"
-- not as a demonstrated +0.075.**

### h28 -> h29-arm is a clean single-variable test, by accident of the reranker

`candidate_file_recall` delta is **exactly 0.000** and `candidate_bundle_complete` moved on **0 of
100** cases. Retrieval is byte-identical between the two runs -- the cross-encoder is deterministic
where the generative reranker is not, so the allowlist's effect is isolated with no noise at all:

- fabrication **0.053 -> 0.031**
- `answer_grounded` **0.730 -> 0.810** (13 up, 5 down, p=0.096)
- primary +0.010

That is the prompt change on its own, measured against a frozen retrieval bundle. Worth keeping in
mind for future prompt work: **pair prompt arms with the cross-encoder, not the generative reranker,
and retrieval noise disappears from the comparison.**

### The guardrail passes, and the interaction that goes with it

`citation_fabricated_rate` 0.031 against a pre-registered bound of **0.035**. Passes. Against the
incumbent's 0.025 the move is +0.007 [-0.016, +0.030] -- within noise on the "must not worsen"
reading too. But the counts show an interaction the means hide:

| | cases with any fabrication | off-list citations |
|---|---|---|
| h17-ctrl | 8 | 10 |
| h28 | 18 | 25 |
| h29-ctrl | **3** | 6 |
| h29-arm | **12** | 16 |

The allowlist is far more effective on the champion (8 -> 3) than on the cross-encoder arm
(18 -> 12). This is exactly the interaction the pre-registration named as a thing to state rather
than explain away: the bound is met, the direction is unfavourable, and neither is resolvable.

Of h29-arm's 16 off-list citations, **15 are real repo files the model was not shown** and only 1
does not exist. The pilot's transcription mode (`prompts.examples/` -> `prompts/examples/`) is a
minor residual at full scale; the dominant residual is plain disobedience of the allowlist.

### Latency, h17-ctrl -> h29-arm

| stage | h17-ctrl s | h29-arm s | delta CI | share h17 | share h29-arm |
|---|---|---|---|---|---|
| plan | 9.33 | 8.05 | [-1.42, -1.15] | 14.0% | 17.9% |
| search | 1.08 | 1.72 | [+0.35, +0.95] | 1.6% | 3.8% |
| rerank | 17.51 | **2.00** | [-15.89, -15.15] | 26.3% | **4.5%** |
| generation | 38.74 | 33.06 | [-7.14, -4.23] | 58.1% | 73.7% |
| total | 66.66 | **44.83** | [-23.49, -20.18] | 100% | 100% |

Against the matched-prompt control run on the same night (h29-ctrl, 54.97 s) the total is **-18.4%**,
which is the drift-free number. The rerank share falls 26.6% -> 4.5% either way.

### Decision: h29-arm is the new champion

Pre-registered guardrail met (0.031 <= 0.035), primary non-inferior and positive on every
comparison, total latency down 18% with the rerank stage now 4.5% of the pipeline. Config:
`configs/context-awareness/protogen-h29-xenc-strict-cite.yml`.

Two things this hands to the next round:

- **Generation is now 73.7% of the pipeline.** Every remaining latency lever is in answer
  generation; retrieval and ranking together are under 26%. The frontier has moved.
- **Fabrication on the arm is the open defect**, not a solved one: 12 cases, 15 real-but-unshown
  citations. The allowlist gets most of the way; the last part is the model ignoring an explicit
  closed set.

## Finding 40 -- generation is prefill-bound, and every excerpt starts at line 1

Diagnosing the 73.7% generation share on the new champion before picking a lever. All from the
h29-arm report, no new runs:

**The answer call is prefill-dominated.** 25,280 input tokens/case against 537 output tokens --
a **47:1 ratio**. Correlation with generation seconds: context chars **+0.51**, prediction chars
+0.31. Prediction length is 1,199 chars mean / 2,307 max, so capping answer length -- the obvious
first lever -- is chasing 2% of the budget. **Context size is the lever.** Context text is 64,785
chars/case, ~7,700 per file across 10 files.

**And then the thing I was not looking for.** Every excerpt in all 981 excerpts across 100 cases
starts at **line 1**:

```
start-line distribution: [(1, 981)]
excerpts at the 160-line cap: 515 / 981 (52%)
```

`AnswerContextBuilder._read_excerpt` anchors at `max(start_line - 20, 1)`, and the index is
file-level by design -- `file_summary` items carry no meaningful start line -- so the anchor is
always 1. **For 52% of the bundle the model reads a file's opening 160 lines and never sees the
rest.** It then explains behaviour that may live anywhere in the file.

This is a gap between the architecture's stated intent and its implementation. The lean file-level
index exists so that a *second, more detailed* pass can work on the selected files. That second pass
currently takes the first 160 lines and stops.

### Two hypotheses, and one is the diagnostic for the other

**H30 (latency, no code):** cut `--context-lines` 160 -> 96 -> 64. Prefill scales with it.

**H31 (quality, needs code):** anchor excerpts on the region of the file that matches the query
instead of on line 1. A lexical window picker over the query tokens is deterministic and needs no
model call. Potentially latency-*negative* as well: two 60-line windows beat one 160-line head.

H30 is worth running first even though H31 is the more interesting fix, because **H30 measures how
much the excerpt content is worth at all.** If 160 -> 96 costs nothing on the primary, the head
excerpt is carrying little information and relevance-anchoring is the fix. If it costs a lot, the
excerpts matter and the truncation is worse than it looks. Either result directs H31.

### Two caveats recorded before the sweep runs

1. **The primary may be structurally blind to what this sweep breaks.**
   `citation_expected_recall` asks whether the right *file* was cited. Truncating an excerpt cannot
   stop a file being cited as long as it stays in the bundle -- so the sweep can look free on the
   primary while degrading the explanation a developer actually reads. `token_f1` / `key_token_f1`
   against the reference are the cheap secondary signals; the judge is disabled in these runs. Any
   "no cost" verdict from H30 must be stated as "no cost *on a citation metric*".
2. **The sweep does not reach 12.2% of the context.** `doc_lines_per_file` is hard-coded at 120 and
   `--context-lines` does not touch it. Documentation is 7,908 of 64,785 chars/case. So a nominal
   160 -> 64 cut is a ~0.4x on the code section and 1.0x on the docs -- the realised prefill
   reduction will be smaller than the flag suggests, and predicted latency must account for it.

### H30 pre-registration

Two arms at 100 cases, sequential, against the h29-arm champion (0.770 primary / 0.031 guardrail /
44.83 s):

- `cl96`: predicted context chars ~44k, total ~38-41 s/case. Primary predicted within noise of 0.770.
- `cl64`: predicted context chars ~31k, total ~34-37 s/case. Primary predicted to start slipping
  here if excerpt content matters at all.
- Guardrail `citation_fabricated_rate` <= 0.035 on both. A shorter bundle gives the model less to
  cite correctly, so this is a real risk, not a formality.
- Secondary, stated in advance so it cannot be picked afterwards: `key_token_f1` vs the champion's
  value. A primary that holds while `key_token_f1` falls is the signature of caveat 1 coming true.

---

## Finding 41 — H31 is feasible and the index does not have to change

Measured while the H30 sweep ran, read-only, with `/tmp/h31-anchor-probe.py`. Two questions had to be
answered before writing any source: *can* an anchor be computed, and *would it move*.

### The index carries no line numbers, and it does not need to

`.code-diver/protogen-h17-ctrl.json` holds 8,843 items — `file_summary` 3,304, `file_manifest` 3,304,
`doc_chunk` 1,159, `doc_summary` 538, `doc_manifest` 538 — with fields
`content, end_line, id, metadata, path, start_line, title`. Every file-level item has
`start_line: null`. That is not a defect: a file-level index is *supposed* to be file-level, and
adding line numbers to it would be exactly the index bloat the architecture forbids.

So the anchor has to be computed at context-build time, on the selected files only — which is
precisely the "later, more detailed pass" the lean index exists to enable. The tool for it is already
in the repo: `CodeSymbolExtractor` (`src/code_diver/services/code_symbol_extractor.py`, 156 lines,
`ast` for Python and regex for JVM/generic) returns `CodeSymbol` with real `start_line`/`end_line`.
`FileOutlineService` already calls it. No new dependency, no model call, no index change.

### The structural gate passes, and not marginally

796 code excerpts across the champion run's 100 recorded bundles, scored by symbol-name overlap with
the question (identifiers split on `_` and camelCase, question words and generic code nouns
stopworded), with a windowed lexical fallback:

| measure | value |
|---|---|
| code excerpts examined | 796 |
| longer than the 160-line window | 501 (62.9%) |
| anchor moves off line 1 | 403 — **80.4% of the truncated ones** |
| by mechanism | symbol match 356, lexical fallback 47 |
| anchor line reached | median 50, p90 305, max 3666 |
| **expected-path excerpts that move** | **78 of 119 (65.5%)** |
| cases where nothing moves at all | 5 of 99 |

The last two rows are the ones that matter. The move lands on the answer-bearing file two times in
three, and only 5 cases are untouched — so the arm is measurable rather than a rounding error. The
p90 of 305 and max of 3,666 say this is a relocation, not a nudge: for those excerpts the champion
window and the H31 window do not overlap at all.

Symbol matching does the work (356 of 403). That ordering was predicted and it held: every case in
this dataset is a `where-*` question, so the answer is a definition site, and a symbol name is a far
stronger locator than token frequency — which in a source file concentrates in the imports at the
top, i.e. where the head window already sits.

### Design, v1 — one window per file, only the anchor moves

`AnswerContextBuilder._read_excerpt` line 115 is the whole lever:
`start_line = max(int(result.item.start_line or 1) - 20, 1)`. Replace the fallback with a
collaborator that scores the file's own symbols against the query:

1. tokenize the question (split identifiers, drop stopwords);
2. `CodeSymbolExtractor.extract` → score each symbol by token overlap with the query;
3. best symbol with a non-zero score → anchor at `max(start_line - 8, 1)`, keeping decorators and
   the docstring above it; ties go to the earlier symbol;
4. no symbol match → highest-scoring window by per-line token hits;
5. nothing scores → line 1, i.e. today's behaviour.

Step 5 matters: the arm degrades to the champion, never to something worse.

Deliberately **not** in v1: multiple windows per file (`file_ranges[path]` is a single tuple, so
multi-window is a separate change and a separate arm), and no change to `doc_lines_per_file` — a
document's opening genuinely is its summary. Holding the window width fixed makes the arm
latency-neutral by construction, which isolates the variable to anchor position alone.

Config: `evaluation.excerpt_anchor: head | relevance`, default `head`. Same discipline as
`restrict_citations_to_context` — the series stays comparable and the report stamps which arm ran.

### A free correctness check, from Finding 39

Paired against the cross-encoder champion, retrieval is deterministic. H31 touches only the prompt
body, so `candidate_file_recall` must come out at delta exactly 0.000 with bundle changes on 0/100
cases. If it does not, something other than the anchor moved and the comparison is void.

### One prediction that was checked and withdrawn before it was registered

The 52% cap-hit rate will *not* fall. `truncated` is true whenever the file is longer than the
window, which is a property of the file and not of the anchor. Cap-hit rate is therefore not a
measure of this change, and the honest structural gate is the anchor-move rate above.

### Wiring, decided before the sweep finished so implementation is mechanical

`AnswerContextBuilder.build(results)` takes no query, so the question has to reach it. Rather than a
boolean plus a query argument, the anchor becomes a collaborator:

```
class ExcerptAnchorSelector(Protocol):
    def anchor(self, path: str, result: SearchResult, query: str) -> int: ...
```

- `HeadExcerptAnchor` — today's `max((result.item.start_line or 1) - 20, 1)`. The default.
- `RelevanceExcerptAnchor` — the symbol/lexical scorer above, falling back to the head anchor.

Injected into `AnswerContextBuilder`; `build(results, *, query: str = "")` keeps the second caller
compiling. This is testable with no config plumbing at all, which is the point.

The scorer needs the file's full text, and `_read_excerpt` only reads *after* the anchor is chosen.
Rather than re-implement the path-guard / ignore / size checks in a second place, add one method —
`ReadExcerptService.full_text(path) -> str` — and hand the selector the same service instance. That
is a second read of each of 10 files per case, page-cached, invisible against 45 s.

`AnswerReportJudge._context_text` (`answer_report_judge.py:155`) also builds a context, from the
*cited* paths, with no question in scope. It stays head-anchored: the judge is disabled in this
series, so it cannot affect the H31 measurement, and changing it would be a second uncontrolled
variable. Noted as a known inconsistency rather than fixed silently.

---

## Finding 42 — the residual fabrication is mostly not fabrication, it is a bundle cap

Task #23 said "12 cases still cite unshown files". Decomposing those 16 off-list citations against
each case's own `retrieved_files` changes what the task is:

| what the off-list citation actually was | count | share |
|---|---|---|
| **retrieved by the search, then dropped from the bundle** | **10** | **62.5%** |
| a real repo file that was never retrieved | 5 | 31.3% |
| a path that does not exist | 1 | 6.3% |

And the 10 dropped ones are *all documentation*: `src/ailoop/README.md`, `src/tools/README.md`,
`tests/auth/TEST_COVERAGE_SUMMARY.md`, `specs/06_pipeline.md`, `specs/21_feature_driven_pipeline.md`,
`prompts.examples/TEMPLATE.md`, `prompts.examples/frontend.md` (twice),
`team-configurator/release/sdk/docs/OFFLINE_INSTALL.md`. The retriever found them, the model wanted
to cite them, and the bundle threw them away.

The cap that threw them away is `AnswerContextBuilder(max_docs=3)`.

### The two knobs that shape the prompt and cannot be set

```
grep -rn "max_docs\|doc_lines_per_file" src/code_diver/cli.py src/code_diver/config/*.py
→ no matches
```

`max_docs=3` and `doc_lines_per_file=120` are constructor defaults, reachable from no config file and
no CLI flag. `--context-files` sets `max_files`; `--context-lines` sets `lines_per_file`; the
documentation half of the bundle has no lever at all. That is the same defect class as task #20's
silently-ignored config fields, and it is also the mechanism behind the earlier measurement that
documentation is 7,908 of 64,785 context chars per case — 3 docs x 120 lines, by construction.

### What this does to task #23

The prompt-engineering ideas recorded for #23 (number the allowlist, repeat the constraint, re-ask
once) were aimed at a model that invents paths. Only 6 of 16 off-list citations are that. The
majority is the pipeline telling the model "cite only what is shown" while withholding documents its
own retriever ranked highly. No amount of prompt pressure fixes that; the model's choice was right
and the bundle was wrong.

The remaining 6 split as 5 plausible code paths inferred from the repo's naming conventions
(`src/app.py`, `src/agents/frontend/models.py`, `src/agents/backend/prompts.py`,
`src/agents/product_manager/factory.py` — the model knows the pattern and guesses the file) and 1
transcription slip (`prompts/examples/api.md` for `prompts.examples/api.md`). Prompt work is the
right tool for those, and it is a 6-citation ceiling, not a 16-citation one.

**Still refused, for the same reason as before:** the fix is to show the files, not to stop counting
the citations. A metric that forgives citing a retrieved-but-unshown file would also forgive citing
anything the retriever happened to touch.

### H32, pre-registered as a task, not yet run

Make `max_docs` and `doc_lines_per_file` configurable, then raise `max_docs` 3 -> 6. Direct conflict
with H30, which is buying latency by shrinking prefill — so H32 must be measured *after* the H30
verdict fixes the code-side budget, and it must be priced in the same currency: the extra documents
cost prefill, and the question is whether they buy more guardrail than they cost in seconds.

---

## Finding 43 — H31 v1 is refuted before it was built, and the head window is why

Finding 41 established that a symbol-anchored window *moves* on 80.4% of truncated excerpts. Moving
is not helping. Two further offline probes asked whether it moves toward the answer, using each
case's human-written `reference` text as the ground truth for "the part of the file that answers the
question" (reference tokens that the question already contains are excluded — they would flatter both
windows equally).

### The relocated window overlaps the answer *less*

`/tmp/h31-window-content-probe.py`, 78 expected-path code excerpts too long to show whole:

| | count | share |
|---|---|---|
| relevance window contains more reference tokens | 2 | 2.6% |
| fewer | 41 | 52.6% |
| tied | 35 | 44.9% |

Mean reference-token hits: head 2.15, relevance 1.46 — a 32% loss.

### And it is not an import-block artifact — the answer really is near the top

`/tmp/h31-where-is-the-answer.py` slides the window across the *whole* file and takes the argmax, so
this is the oracle: the best any anchor could ever do. 88 expected-path long files:

| measure | value |
|---|---|
| oracle best window starts in the first 30 lines | **55 (62.5%)** |
| oracle best-window start | median **line 1**, p90 442, max 2329 |
| share of the oracle's reference tokens the head window already captures | **77.2%** |
| mean tokens a *perfect* anchor would add over the head | **3.80** |
| header-stripped head (lines 31-160) vs relevance window | relevance more 16.7%, fewer 21.8%, tied 61.5% |

The last row rules out the obvious confound. If the head window only won because imports and the
module docstring are dense in the vocabulary a human reference uses, then deleting the header should
hand the win to the relevance window. It does not — stripped of its header the head window is still
roughly tied with the relocated one. The header contributes, and so does the rest of the top.

The reason is structural, and it is the same reason the lean file-level index works at all: Python
puts the imports, the class statement, its docstring and `__init__` at the top, and a `where is X`
answer is mostly "in class Y in module Z" — vocabulary that lives in the header. The architecture's
premise that a file's identity is legible from its opening is **empirically sound on this corpus**.

### What survives

Not "move the window" but "keep the head *and* add the matching region" — the multi-window variant
that was explicitly deferred out of v1 in the design above. The head carries 77.2% of the oracle's
reference tokens; the missing 22.8% is real and is what the second window would buy. 37.5% of these
files have their oracle window elsewhere entirely, p90 at line 442, so the second window has
somewhere to go.

Its ceiling is now known and it is small: **+3.80 reference tokens, +22.8% of oracle coverage** — and
unlike v1 it costs prefill, which puts it in direct conflict with H30. `file_ranges[path]` being a
single tuple also means it is a larger change than v1 was.

### Three caveats on this refutation, stated so it is not over-read

1. Reference-token overlap is a proxy. A reference is prose about concepts; a code window is code.
   The absolute counts are single-digit tokens, which is a weak instrument even at n=88.
2. It measures *vocabulary* presence, not whether the shown lines let a model answer. A window can
   contain the right identifiers and still not show the construction site.
3. The series' primary is a *citation* metric. If H30 shows it flat from 160 to 64 lines, then
   excerpt content barely moves the primary at all, and no excerpt-shaping arm should be judged on
   it — `key_token_f1` or a judge would have to be promoted to primary first. That decision belongs
   to the H30 verdict, not here.

**Cost of finding this out: ~10 minutes of CPU on two throwaway probes, instead of ~45 minutes of GPU
on an arm that would have lost.** That is the argument for making the structural gate a quality gate
before writing source, not after.

---

## Finding 44 — H30 verdict: neither arm promotes, and the excerpt content is worth real primary

Both arms, 100 cases, matched pairs against the h29-arm champion. Determinism check from Finding 39
passed on both: `candidate_file_recall` delta exactly **0.000**, bundle changes **0/100** — only the
prompt moved, so retrieval noise is zero and every delta below is attributable to excerpt width.

| arm | context chars | primary | delta vs champion | guardrail | s/case | latency | generation share |
|---|---|---|---|---|---|---|---|
| champion cl160 | 64,785 | 0.770 | — | 0.031 | 44.83 | — | 73.7% |
| cl96 | 48,951 | 0.745 | −0.025 **[−0.057, +0.007]** | 0.028 | 39.46 | −12.0% | 68.5% |
| cl64 | 39,895 | 0.735 | −0.035 **[−0.067, −0.003]** | 0.026 | 35.05 | −21.8% | 65.5% |

cl96 vs cl64 directly: primary −0.010 [−0.054, +0.034] — the two arms are not distinguishable from
each other, only from the champion.

### Verdict

**Neither promotes.** cl64's primary loss is resolvable (CI excludes zero). cl96's is not, but its
point estimate is negative and it sits monotonically between the champion and cl64, which is weak
evidence the loss is real rather than noise. Under the H16 rule — rank on the primary, it must not
fall — the champion stands at cl160.

**cl96 is nonetheless a legitimate Pareto point and is recorded as one:** −12.0% wall-clock for a
primary loss that this experiment cannot resolve from zero. The stated goal is a latency/quality
frontier, not a single champion, and an arm that buys 5.4 s/case for an unresolvable 0.025 belongs on
that frontier even though it does not take the crown.

### The diagnostic question H30 was really run to answer

H30 existed to tell H31 whether excerpt content is worth anything. The answer is **yes, and the
primary can see it**: cutting the window costs resolvable primary. That reverses the pre-registered
caveat 1, which worried the primary would be structurally blind to truncation damage. It is not
blind — it was the *only* metric that moved.

The pre-registered secondary behaved the opposite way to the predicted failure signature:

| | champion | cl96 | cl64 |
|---|---|---|---|
| `key_token_f1` | 0.1147 | 0.1128 (−0.0019, CI spans 0) | 0.1203 (+0.0055, CI spans 0) |
| `token_f1` | 0.1189 | 0.1165 | 0.1243 |

Caveat 1 predicted "primary holds while `key_token_f1` falls". What happened is primary falls while
`key_token_f1` holds or drifts up. So the two metrics are measuring genuinely different things —
citations respond to how much the model was shown, answer prose does not — and neither is a
substitute for the other.

### Both latency predictions landed inside their windows; both context predictions did not

Predicted 38-41 s for cl96 (actual **39.46**) and 34-37 s for cl64 (actual **35.05**). Both hit.

Context chars were predicted at ~44k and ~31k; actuals were 48,951 and 39,895 — both high. Caveat 2
called the direction correctly (documentation is fixed at 3 x 120 lines and the flag does not reach
it) but understated the size. The second reason is Finding 41's measurement: only 62.9% of code
excerpts are longer than 160 lines at all, so narrowing the window does nothing to the other 37.1%.
A nominal 160→64 is a 0.40x on the flag and a realised **0.62x** on the prompt.

### The pre-registered fabrication risk did not materialise

"A shorter bundle gives the model less to cite correctly, so this is a real risk, not a formality."
The guardrail moved the other way on both arms (0.031 → 0.028 → 0.026), neither resolvable. Recorded
as a wrong prediction, not as a win.

### What this does to the frontier and to the next target

Generation share falls 73.7% → 68.5% → 65.5%, and `plan` is flat at ~8.06 s in absolute terms across
all three arms — which makes it **23.0% of cl64**, the second-largest stage and the largest one that
has never been attacked. As generation shrinks, the planner becomes the next lever (task #17 already
holds a premise for it: 73.2% of the planner's path-like probe tokens do not exist in the repo).

For task #24: the primary responds to excerpt content, so an excerpt-shaping arm *is* judgeable on
the primary, and no metric promotion is needed first. And since removing content costs primary,
adding the right content may gain it — which is the case for the surviving head-plus-relevance-window
variant. Its measured ceiling is +22.8% of oracle reference-token coverage, and it costs prefill,
which H30 has now priced at roughly **2.3 s per 10k context chars**.

---

## Finding 45 — the dataset has no reference answers, and the judge found it before we did

Prompted by the observation that character-level overlap is the wrong instrument for explanation
quality, the disabled judge was wired up and calibrated before being trusted. The calibration
uncovered something larger than the judge.

### The judge works, after two fixes

1. **Gemma-4-12B cannot be served by this `mlx_lm`** (`ValueError: Model type gemma4_unified not
   supported`). Served the QAT GGUF via `llama-server` on the judge-reserved :8030 instead, under a
   new config `configs/answer-judge-local-gemma4-12b-gguf.yml` that names the quantization actually
   on the wire rather than borrowing the mlx repo id.
2. **Every judgement was being thrown away by the schema validator.** `JsonSchemaValidator` treats a
   blank `required` property as a violation, and the strict prompt tells the judge to leave
   `critical_issues` empty when all six criteria score 4/4. A complete, correct judgement was
   discarded as an error, three times out of three. Fixed with an `allowEmpty` keyword: the property
   stays required, so a dropped key is still caught, but an empty value is accepted. The keyword is
   stripped at the wire boundary (`_without_local_keywords`) because it is this repo's invention and
   llama.cpp compiles the schema into a grammar. 4 tests added, 1016 passing.

### Calibration: the judge discriminates, weakly, and disagrees with the primary

11 cases spanning the primary's range:

| citation_expected_recall | n | judge_overall |
|---|---|---|
| 0.00 | 5 | 3.69 – 4.81, mean 4.29 |
| 1.00 | 6 | 4.81 – 5.00, mean 4.94 |

Separation exists but the whole scale is compressed into the top 26% of its range, and two cases
with recall **0.00** scored **4.81/5**. That looked like a lenient judge. It is not.

### `where-authorization`: the judge is right and the answer key is wrong

- **Question:** "where is authorization authentication user permissions tokens handled"
- **`expected_paths`:** `src/config/settings.py`, `src/api/routes/settings.py`,
  `src/operators/models_config.py` — three *settings* files.
- **What the model answered:** the `app_platform/backend/auth` module — `AuthService` for
  registration/login/JWT, `RBACService.check_permission()`, the RBAC router, dependencies and models,
  roles in `resource:action` form. Grounded, specific, correct.
- **`citation_expected_recall`: 0.00.** The metric scored a correct answer zero.
- The judge gave 4.81 and put the disagreement in `critical_issues` rather than swallowing it: *"The
  answer does not mention the specific files listed in the reference answer."*

### And then the general case

```
reference is the auto-generated stub: 100/100
```

Every `answer` field in `datasets/protogen_answer_cases_100.jsonl` is the same template:

> `Relevant implementation files: <paths>. These files should be used as evidence to answer the
> repository question.`

**There are no reference answers in this dataset.** There is a path list wrapped in a sentence.
Three consequences, and all of them touch results already recorded:

1. **`token_f1` / `key_token_f1` were comparing generated prose to a template sentence.** That is why
   they sat at 0.11-0.12 across every arm and barely moved — nothing in the arm can change the
   overlap with boilerplate. Every reading of them in this document is void, including the H30
   secondary. They should be deleted from the report, not merely demoted.
2. **The strict judge prompt says "Use the reference answer as ground truth"** and its coverage rule
   is "if the answer misses anything from the reference, cap coverage at 3". Fed a path list, the
   judge's coverage criterion degenerates into a fuzzy restatement of `citation_expected_recall`.
   That is precisely the 3.0 coverage scores above. The judge cannot be a second, independent axis
   while it is handed the first axis as its ground truth.
3. **`citation_expected_recall` — the primary of the entire series — is scored against an answer key
   that is sometimes wrong.** All 163 expected paths do exist in the repo, so they are not invented;
   they were derived, plausibly from an earlier retrieval run, and never checked by a human.
   `where-authorization` is one demonstrated failure out of 11 cases inspected.

### What this does and does not invalidate

**Does not:** the paired A/B comparisons. Every arm was scored against the same biased key, and a
consistent bias largely cancels in a matched-pair delta. H28's guardrail failure, H29's promotion and
H30's monotone primary loss all survive as *relative* results.

**Does:** every absolute level. "0.770 primary" is not "77% of questions answered correctly" — it is
77% agreement with an unvalidated key. And nothing recorded in this series measures explanation
quality, because the only two candidates were a citation metric and overlap with boilerplate.

---

## Finding 46 — the reference-free judge removes the bias and the signal together

User's call after Finding 45: build the explanation axis reference-free, scoring the answer against
the **question + retrieved context** only. Written as `prompts/code-answer-judge-context-only.md`,
same six criteria names so `JUDGE_SCHEMA`, `AnswerJudgeRubric` and the payload validator are
untouched. Coverage redefined as "of the question-relevant material present in the context, how much
did the answer use", with an explicit non-goal: the judge cannot see retrieval error, which stays on
the search axis where it belongs.

Calibrated on the same 12 rows as the strict prompt, so every difference is the prompt.

| | strict | context-only |
|---|---|---|
| mean `judge_overall` | 4.672 | 4.984 |
| sd | 0.447 | **0.052** |
| min / max | 3.687 / 5.000 | 4.812 / 5.000 |
| share of the 0–5 range used | 26.3% | **3.8%** |
| corr with `citation_expected_recall` | 0.726 | 0.357 |
| coverage sd | 0.954 | **0.000** |
| `critical_issues` raised, 12 cases | 7 | **0** |

**It worked as designed.** All five recall-0.00 cases stopped being punished for missing a wrong
answer key: `where-eval-runner` 3.69 → 4.81, `where-pipeline-built` 3.87 → 5.00, `where-authorization`
4.81 → 5.00. Coverage went to 4.0 everywhere. Correlation with the search axis dropped by half.

**And it is useless.** 11 of 12 cases scored exactly 5.00. Zero errors, zero context overflow (max
~22k tokens against a 32768 window), so this is the model's real verdict, not a failure.

The reason is visible in the strict run's own per-criterion means: `evidence_grounding`,
`citation_quality`, `specificity` and `hallucination_control` were **already** pinned at 4.00 under the
strict prompt. Every bit of the strict judge's variance came from `coverage` (sd 0.954) and
`answer_correctness` — exactly the two criteria whose rules cited the reference. Remove the reference
and Gemma-4-12B has no complaint of its own. This is not a prompt-wording problem: an absolute rubric
with this judge has no discriminative power to recover.

Projected cost of the planned 3-arm absolute run: 5.7 h of GPU (12 cases = 14.6 min) to produce three
numbers near 4.98 ± 0.05. Not run.

## Finding 47 — the common yardstick, and why H30 forces it

A reference-free judge grades an answer against the context it was shown. H30 is a context-**length**
sweep. Judge each arm on its own context and the instrument goes blind to the effect under test: an
arm shown 64 lines per file has less to be incomplete about than one shown 160, so a thinner answer
over a thinner context earns full coverage. The three arms would come out equal by construction, and
that equality would be an artifact of the method.

So all arms are judged against **one** context: the champion cl160's. Verified, not assumed:

- context windows all start at line 1 (`file_manifest` items carry `start_line: null`), so cl160's
  window is a strict prefix-superset of cl96's and cl64's;
- code content of the short arms is contained in the champion's on every case — the only lines that
  looked "extra" were the builder's own `Excerpt: path:1-64` header lines;
- `context_files` are identical as a **set** on 93/100 cases (cl96) and 95/100 (cl64); the ordering
  differs more often, which is irrelevant here.

**93 of 100 cases** survive as ones where the champion context covers *both* short arms. The other 7
are dropped rather than patched, because there the superset property fails and a short arm would be
accused of inventing a real file: `where-arena-repository`, `where-calculator-api`,
`where-codegen-tools`, `where-command-created`, `where-health-checks`, `where-python-package`,
`where-sample-apps`.

What the substitution buys: `coverage` becomes truncation-sensitive and `hallucination_control` stays
fair. What it costs: the scores stop meaning "how faithful was this answer to what it was given" and
start meaning "how good is this answer against the best available view of the code". The second is
the Pareto question, so that is the right trade — but it must not be read as the first.

`AnswerPairwiseReport` enforces the identical-context invariant in code
(`MismatchedPairwiseContextError`), so this cannot be got wrong silently later.

## Finding 48 (pre-registered) — pairwise forced choice as the explanation axis

User's call: pairwise. The instrument is a forced choice between two answers to the same question over
the same context — it cannot saturate the way an absolute rubric did, because the judge must name a
side. Built as `prompts/code-answer-pairwise.md`, `PAIRWISE_SCHEMA`, `AnswerPairwiseJudge`,
`AnswerPairwiseReport`, and the `answer-pairwise` CLI command. 1035 unit tests pass (was 1016).

Design decisions worth keeping:
- **Slot alternation.** LLM judges favour whichever answer they read first. The baseline takes slot A
  on even case indices and slot B on odd ones, and the realised `slot_a_win_share` is printed every
  run as a bias diagnostic (0.5 = unbiased).
- **An unreadable verdict is an error, not a tie.** Folding parse failures into the tie bucket would
  bias every aggregate toward "no difference" — the one conclusion the instrument exists to test.
- **Sign test over discordant pairs only**, matching the rest of the series.

Smoke, 6 cases, cl64 vs cl160: 6/6 judged, 0 errors, **0 ties** at the overall level, margins in use
(2 clear, 4 slight), rationales that name specific classes. 75 s per comparison.

**Sequencing.** cl64 vs cl160 runs first — the widest contrast, and the arm carrying H30's −0.035
primary loss for its −12% latency win. cl96 is bracketed by it: run only if cl64's result makes the
frontier's bend worth locating. n=93, ~2 h.

**Pre-registered predictions (written before the run finished):**

1. **cl64 loses overall, but not decisively.** Expect roughly 30–40 arm wins, 45–55 losses, few ties;
   `sign_test_p` between 0.05 and 0.30. Rationale: the smoke split 3–3, but H30 already showed a real
   monotone primary loss, and the yardstick now exposes the truncated arm to code it never saw.
2. **`coverage` is the dimension that moves; `correctness` is not.** cl64 should lose coverage most
   clearly. If instead `correctness` carries the loss, truncation is corrupting answers rather than
   thinning them, and that is a much worse result for the whole latency story.
3. **`slot_a_win_share` lands in 0.40–0.60.** Outside that, the arm-level numbers are soft and the
   run needs an order-swapped replication before anything is promoted.
4. **`critical_errors` stay near zero for both arms.** H29's cite-only-shown-files constraint already
   drove `citation_path_valid_rate` to 1.0; if the pairwise judge starts finding fabrications the two
   instruments disagree and the guardrail needs re-examining.
5. **Margins skew `slight`.** Both arms run the same generator over the same files; only the window
   length differs. A `decisive` verdict rate above ~15% would suggest the judge is manufacturing
   distinctions rather than finding them.

---

## Finding 49 — the explanation axis resolves what the retrieval primary could not: cl96 survives, cl64 is refuted

Both pairs run, n=93 each, 0 judge errors, ~115 min each, every answer judged against the common
cl160 yardstick from Finding 47.

| arm vs cl160 | arm wins | cl160 wins | ties | win rate (decided) | sign p | slot A share |
|---|---|---|---|---|---|---|
| **cl64** | 26 | 67 | 0 | 0.280 **[0.199, 0.378]** | **2.53e-05** | 0.527 |
| **cl96** | 43 | 48 | 2 | 0.473 [0.373, 0.574] | 0.675 | 0.495 |

Per dimension (arm wins / cl160 wins / ties, sign p):

| dimension | cl64 | cl96 |
|---|---|---|
| correctness | 3 / 12 / 78, p=0.035 | 3 / 8 / 82, p=0.227 |
| grounding | 20 / 65 / 8, **p=1.03e-06** | 38 / 45 / 10, p=0.510 |
| coverage | 28 / 62 / 3, p=4.4e-04 | 41 / 46 / 6, p=0.668 |
| specificity | 25 / 65 / 3, p=3.0e-05 | 42 / 45 / 6, p=0.830 |

Margins: cl64 0 decisive / 27 clear / 66 slight; cl96 0 decisive / 17 clear / 76 slight.
Critical errors: cl64 **18** vs cl160 7; cl96 **11** vs cl160 9.

### Why this matters more than the numbers themselves

On the retrieval primary these two arms were **not separable**: cl96 vs cl64 was −0.010 [−0.054,
+0.034] (Finding 44). The explanation axis separates them cleanly — cl64 at p=2.5e-05, cl96 at
p=0.675. The new instrument therefore carries information the primary does not, which is the whole
reason it was built. It is not a prettier restatement of `citation_expected_recall`.

Consequences for the frontier:
- **cl96 is confirmed as a Pareto point.** −12.0% wall-clock, an unresolvable −0.025 primary, and now
  an explanation quality indistinguishable from the champion. Its residual risk is bounded: the
  decided-win-rate CI's lower edge is 0.373, so the largest hidden loss consistent with the data is
  modest, not a silent collapse.
- **cl64 is refuted, and refuted on quality rather than on the primary.** Its −21.8% latency was the
  most attractive number in H30. It is not available.
- **The bend in the frontier lies between 64 and 96 excerpt lines.** Locating it more precisely would
  need a cl80 arm; not worth 2 h of judge time unless the latency delta between cl96 and cl80 is
  itself material.

### Mechanism: truncation makes the generator vaguer, not wrong

cl64 ties `correctness` on 78/93 while losing `grounding` 20–65. Truncation does not corrupt answers;
it makes them speculative. The tagged critical errors are exactly that shape — claims about code that
*is* in context but was misread: a default model given as `anthropic/claude-3-5-sonnet` when the file
sets `gpt-5.2-codex`, a router described as mounted at root when `src/app.py:109` sets
`prefix="/api/v1"`, line ranges cited that do not contain what is claimed, `execute_task` named where
the context has `execute`.

### Prediction scoring

1. **WRONG (magnitude).** Predicted 30–40 cl64 wins and p between 0.05 and 0.30. Actual 26 wins,
   p=2.5e-05. The loss is far stronger than predicted. Lesson: the yardstick change is not a minor
   methodological tidy-up — exposing a truncated arm to code it never saw is a substantial extra
   penalty on top of its own thinness, and I under-weighted it.
2. **PARTIALLY RIGHT (dimension).** Correct that `correctness` would not carry the loss. Wrong that
   `coverage` would be the driver: it is **grounding** (p=1.03e-06 vs coverage's 4.4e-04). The
   distinction is real and useful — coverage is "said less", grounding is "said it less
   defensibly", and the second is the worse failure.
3. **RIGHT.** `slot_a_win_share` 0.527 and 0.495, both inside [0.40, 0.60]. No order-swapped
   replication needed.
4. **WRONG.** Predicted `critical_errors` near zero for both arms. Actual cl64 18 / cl160 7, cl96 11 /
   cl160 9. This does **not** contradict `citation_path_valid_rate = 1.0` from H29, and the two
   instruments are not in conflict: H29 measured whether a cited path exists and was shown, the
   pairwise judge measures whether the *claim about* that path is true. A file can be real,
   in-context, and still described wrongly. **The guardrail has a blind spot, not a bug** — and the
   fact that even the champion accrues 7–9 such errors per 93 cases is a standing quality issue
   independent of context length.
5. **RIGHT.** 0 decisive verdicts in either run; margins skew `slight` (66/93 and 76/93). The judge is
   finding distinctions, not manufacturing them.

Two of five wrong is a fair rate for a first run on a new instrument, and both misses were in the
direction of under-estimating how much the instrument would find.

### Standing caveat on the whole axis

Every number above is *relative* — "better than the other answer on the champion's context". The
absolute rubric saturated (Finding 46), so there is still **no absolute measure of explanation
quality** in this project, only an ordering. A pairwise result cannot tell us whether cl160's answers
are good; it tells us cl64's are worse. Treat any future claim about absolute answer quality as
unmeasured until a discriminating absolute instrument exists.

### Reports

- `.code-diver/reports/protogen-h30-pairwise-cl64-vs-cl160-93.json`
- `.code-diver/reports/protogen-h30-pairwise-cl96-vs-cl160-93.json`
- Yardstick inputs: `/tmp/judge-yardstick/{cl160,cl96,cl64}-yardstick.json` (**in /tmp — regenerate
  from `/tmp/build-common-yardstick-reports.py` if needed, or promote them if the axis is re-run**)

---

## Finding 50 — we have been attacking the smallest term: the primary's ceiling is the rerank pool

Before spending another 75-minute eval arm, I decomposed the primary gap from data already on disk
plus one cheap retrieval replay (`scripts/replay_pool_recall.py`, 1.4 s/case, no generation).

Champion (`protogen-h29-xenc-strict-cite-100-cf10-cl160`), 100 cases:

| quantity | value | what it bounds |
|---|---|---|
| raw merged pool recall @34 | 0.859 | what the cross-encoder is even allowed to see |
| `candidate_file_recall` (reranked top-10) | 0.805 | what the context builder receives |
| `context_file_recall` | 0.805 | context builder loses **nothing** |
| `citation_expected_recall` (**primary**) | 0.770 | what the answer cites |

**Loss budget on the 0.230 gap to a perfect primary:**

1. **Pool depth — 0.141.** Expected files that never enter the 34-candidate pool at all.
2. **Rerank cut 34→10 — 0.054.** In the pool, discarded by the cut.
3. **Generation/citation — 0.035.** Shown to the model, not cited.

Raw pool recall by depth: 0.650@10, 0.736@14, 0.791@20, **0.859@34**, **0.908@60**, **0.926@80**.

### The uncomfortable part

Term 3 is the smallest by a factor of **4**, and term 3's neighbourhood is where H29, H30, H31 and
the whole explanation axis were spent. The context builder loses exactly zero — `context_file_recall`
equals `candidate_file_recall` to three decimals — so widening the context (H32-as-ticketed,
`max_docs` 3→6) cannot fix anything that is actually broken. Task #25's framing was wrong and is
superseded.

Meanwhile the cross-encoder rerank is **2.0 s of 44.9 s (4.5%)** of wall-clock. Deepening the pool
34→60 is ~1.8× that stage, roughly **+1.6 s (+3.5%)**, in exchange for a ceiling that rises by
+0.049. That is by far the best latency-per-quality trade left on the board, and it is the one knob
nobody has touched.

Note also what the reranker is already worth: it converts a raw-order recall@10 of **0.650** into
**0.805**. It is not a marginal stage — which is exactly why giving it more to work with is worth
testing before assuming more distractors will drown it.

### Instrument: `scripts/replay_rerank_depth.py`

`replay_pool_recall.py` deliberately peels the rerank off, so it can measure term 1 but is blind to
term 2. The new script replays the real probe queries and then runs the **real**
`AnswerCandidateCrossEncoderReranker` over the merged pool at several `candidate_limit` values,
reporting post-rerank recall at several cuts. No planner call, no generation, ~4 s/case — a
(3 depth × 3 cut) grid costs under an hour instead of three 75-minute eval arms.

Fidelity: probes are re-fetched per depth with `query_limit = max(limit, depth)` exactly as
`AnswerEvaluator._retrieve` computes it, and the rerank query is `case.question`, not a probe query.

### Finding 50a — retrieval replay is NOT bit-deterministic; the reranker is

Two identical 5-case replays produced **different merged pools on 2/5 cases** (one differing at rank
1, one at rank 32) while the reranked top-10 was **identical on 5/5**. A separate check across two
runs at different `--cuts` also showed the top-10 diverging.

This qualifies Finding 39 rather than overturning it. Finding 39's claim — retrieval noise exactly
zero — was measured across H30's *prompt-side* arms in the live pipeline, and held there (`delta
0.000`, bundle changes 0/100). It does not license treating a **re-executed** retrieval as
noise-free. Every depth comparison in this grid therefore ships with a same-depth replicate as its
noise floor, and no depth delta gets promoted unless it clears that floor.

Practical consequence for the prefix-stability shortcut the script takes (one rerank call at the
largest cut, scored at every smaller cut): the assumption is documented in the code with an
instruction to re-verify, because the check that would have falsified it is confounded by this
retrieval noise and so cannot currently confirm it either.

### H32 pre-registered predictions (written before the grid finished)

1. **Deepening helps, but converts at well under 100%.** Reranked recall@10 rises from ~0.805 to
   roughly **0.83 at depth 60** and **0.84 at depth 80** — capturing about half the pool-recall gain.
   Rationale: the reranker already leaves 0.054 of the *current* pool behind, and deeper pools add
   both harder targets and 26–46 more distractors.
2. **It does not go backwards.** Reranked recall@10 at depth 60/80 is **not below** the depth-34
   value. If it is, that explains why 34 shipped and kills this direction outright.
3. **Widening the cut beats deepening the pool, per unit of quality.** Depth 34 / cut 14 gains more
   than depth 60 / cut 10. Rationale: term 2's 0.054 is already in the pool and costs no extra
   rerank, only context.
4. **Noise floor ≤ 0.01** on reranked recall@10 between the depth-34 replicate and the grid's
   depth-34 cell.
5. **The ceiling moves a lot.** The best cell (depth 80, cut 20) reaches **≥0.88** reranked recall —
   about 3× the total headroom that every context-side experiment so far has been competing for.

Only after the grid names a winner does a full eval arm get spent, and the arm should be paired with
cl96 from Finding 49 so the extra rerank and context cost is funded by an already-free latency win.

---

## Finding 51 — the cut, not the depth: deeper pools make a narrow cut *worse*

Grid complete, 100 cases, `/tmp/h32-grid.json`. **Macro-averaged**, which is the pipeline's own
convention: the depth-34 / cut-10 cell reproduces the live `candidate_file_recall` of **0.805 to
three decimals**, so the replay is faithful and the two numbers are directly comparable. (Micro
averages run ~4pp lower; do not mix them.)

| pool depth | cut 10 | cut 14 | cut 20 | pool ceiling | rerank s/case |
|---|---|---|---|---|---|
| **34 (shipped)** | **0.805** | **0.865** | 0.870 | 0.883 | 2.04 |
| 60 | 0.790 | 0.860 | 0.890 | 0.928 | 3.33 |
| 80 | 0.755 | 0.845 | **0.895** | 0.943 | 4.33 |

### Three readings

1. **At a fixed cut of 10, deeper pools are monotonically worse** — 0.805 → 0.790 → 0.755. This is
   the opposite of the direction Finding 50 was written to pursue. The pool ceiling does rise
   (0.883 → 0.943), but the cross-encoder cannot hold its top-10 against 26–46 extra distractors.
   This is almost certainly why 34 shipped, and it means "raise `final_rerank_candidate_limit`" —
   the headline recommendation of Finding 50 — is **wrong on its own**.
2. **Depth and cut must move together or not at all.** Deepening only pays once the cut widens to
   20, and depth 80 then buys +0.005 over depth 60. Depth without width is negative; width without
   depth is strongly positive.
3. **The cheap win is the cut.** Depth 34 / cut 14 = **0.865**, +0.060 over shipped, at *zero* extra
   rerank cost — the cross-encoder still scores 34 documents, it is simply asked to return 14 of
   them. The only cost is four more files of context.

### Finding 51a — the instrument's noise floor is 0.000, and per-case churn is recall-neutral

The depth-34 replicate reproduced the grid's depth-34 cell **exactly at all three cuts** (macro
0.8050 / 0.8650 / 0.8700, delta +0.0000). This is not a duplicate run: **50/100 cases had a
different merged pool** and **31/100 a different reranked list** — e.g. `where-ailoop-optimize`
swaps ranks 1 and 2. **Zero cases changed recall@10.**

So the Finding 50a nondeterminism is real but reorders candidates *within* an equivalence class:
churn between two non-expected files, or between two expected ones. The metric does not see it.
Noise floor for the depth grid: **≤0.001 at n=100**, far below every delta in the table.

This also retroactively validates the script's prefix-stability shortcut — one rerank call at the
largest cut, scored at every smaller cut — since the cut-10 column reproduces the live pipeline's
top-10 recall exactly.

### Prediction scoring (Finding 50's five)

1. **WRONG, and wrong in sign.** Predicted reranked recall@10 ≈0.83 at depth 60 and ≈0.84 at 80.
   Actual 0.790 and 0.755 — *below* the 0.805 baseline. I predicted deepening would convert at ~50%;
   it converts negatively at a fixed cut.
2. **REFUTED.** I explicitly predicted it would not go backwards, and named that as the outcome
   that would kill the direction. It went backwards. The direction as stated is dead; what survives
   is the reformulation in reading 2.
3. **RIGHT, and by a wide margin.** Depth 34 / cut 14 (0.865) beats depth 60 / cut 10 (0.790) by
   0.075. Widening the cut is strictly better than deepening the pool, per unit of anything.
4. **RIGHT, stronger than predicted.** Predicted noise ≤0.01; actual 0.000.
5. **RIGHT.** Best cell (depth 80 / cut 20) = 0.895 ≥ 0.88.

Two of five wrong again, and — as in Finding 49 — the misses were on *magnitude and direction of the
mechanism*, not on the instrument. The pattern across both findings is that my priors about how a
model behaves under more/less material are unreliable, while my priors about measurement are sound.
Worth remembering the next time a prediction feels obvious.

### What Finding 50 got right, and what it got wrong

Right: the loss decomposition, and the conclusion that context *width* (`max_docs`) is a dead end.
Wrong: the fix. The ceiling is not raised by giving the reranker more candidates; it is raised by
letting more of the reranker's existing output through to the generator.

---

## Finding 52 (pre-registered) — H32 arms: a 2x2 on excerpt length x context cut

The two new arms complete a factorial with data already on disk, so the cut and the excerpt length
can be separated rather than confounded:

| | cut 10 | cut 14 |
|---|---|---|
| **cl160** | champion, primary 0.770, 44.83 s/case | **H32-A (new)** |
| **cl96** | H30 cl96, primary 0.745, 39.46 s/case | **H32-B (new)** |

Both new arms keep `final_rerank_candidate_limit` at 34 (Finding 51 reading 1) and raise both
`--limit` and `--context-files` to 14 — `--context-files` alone would be a no-op, since the
reranker would still only return 10 results for the builder to draw from.

**Retrieval is identical across all four cells at a given cut**, so both cut-14 arms share the same
ceiling of 0.865, and the cut-10 cells share 0.805. That makes *conversion* — primary ÷ ceiling —
directly comparable: cl160 converts at 0.957 (0.770/0.805), cl96 at 0.925 (0.745/0.805).

Context size: cl96 at 14 files ≈ 68.5k chars vs the champion's 64.8k at 10 files of 160 lines — a
~6% increase, so H32-B should be close to latency-neutral against the champion. H32-A is ~40% more
context and will be clearly slower.

**Pre-registered predictions:**

1. **H32-A primary lands in [0.79, 0.83]**, point estimate 0.815, with the paired CI against the
   champion excluding zero. This is the direct test of Finding 51.
2. **H32-B primary lands in [0.76, 0.81]**, point 0.785 — above the champion, by less than H32-A.
3. **Conversion falls at cut 14 for both arms, but by ≤0.04.** Showing 14 files instead of 10
   dilutes attention; if conversion instead *holds* at 0.957/0.925, the primary gain is the full
   +0.060 and the dilution worry was unfounded. If conversion falls by more than 0.04, widening the
   cut is self-defeating and the frontier stays where it is.
4. **`citation_fabricated_rate` does not exceed 0.05** (champion 0.031). More shown files means more
   legitimate targets, so it should fall if it moves at all.
5. **Latency: H32-A is +20–30% wall-clock vs the champion; H32-B is within ±8%.**
6. **`citation_count` rises from 4.22 toward ~5.**

Decision rule is unchanged (H16): rank on the primary, it must not fall. If H32-B clears the
champion on the primary while staying latency-neutral, it takes the crown outright — and cl96's
explanation quality is already known to be indistinguishable (Finding 49), so that promotion would
not need a new pairwise run. H32-A winning on primary but costing 25% more latency makes it a
frontier point, not a champion.

Deferred: depth 60 / cut 20 (offline ceiling 0.890) — only worth an arm if cut 14 pays off, since it
doubles context against the champion and adds 1.3 s of rerank.

---

## Finding 53 — H32 verdict: mechanism proven, primary underpowered, and the bottleneck has moved

Both arms complete, 100 cases, 0 errors.

| cell | primary | delta vs champion | guardrail | ceiling | conversion | s/case | latency |
|---|---|---|---|---|---|---|---|
| champion cl160/cut10 | 0.770 | — | 0.031 | 0.805 | 0.957 | 44.83 | — |
| h30 cl96/cut10 | 0.745 | −0.025 | 0.028 | 0.805 | 0.925 | 39.46 | −12.0% |
| **H32-A cl160/cut14** | **0.810** | **+0.040 [−0.008, 0.088]** | **0.020** | 0.865 | 0.936 | 58.11 | **+29.6%** |
| **H32-B cl96/cut14** | 0.780 | +0.010 [−0.038, 0.058] | 0.024 | 0.865 | 0.902 | 47.25 | +5.4% |

### The offline instrument was exactly right

The grid predicted a cut-14 ceiling of **0.865**. Both live arms delivered `candidate_file_recall`
= **0.8650**, identical to each other to four decimals. `scripts/replay_rerank_depth.py` is
validated end-to-end: it predicts live retrieval at 4 s/case instead of 75 min, and it should be the
first stop for every future retrieval-side hypothesis.

### Mechanism: unambiguous. Primary: not resolved.

- `candidate_file_recall` +0.060 [0.028, 0.092] — CI excludes zero.
- `candidate_bundle_complete` 0.700 → 0.790, **9 up / 0 down, p=0.0039**. Not one case got a worse
  bundle.
- Guardrail *improved* on both arms (0.031 → 0.020 / 0.024).
- Primary +0.040, but **CI [−0.008, 0.088] includes zero** and the matched-pair sign test gives
  **13 up / 5 down / 82 ties, p=0.096**.

0.810 is the best primary this series has recorded. It is still not a resolvable gain, and 82 ties
mean only 18 discordant cases carry the whole test — this dataset cannot resolve a +0.04 effect. The
blocker is statistical power, not the effect.

**Neither arm promotes.** H32-A is a strong frontier point (best primary, best guardrail, +29.6%
latency). H32-B is a wash on the primary (+0.010, p=0.61) and does not justify itself.

### The 5 regressions are pure dilution, and they are the whole story

The cut-14 context is a strict **superset** of the cut-10 context on **98/100** cases — the reranker
returns the same top-10 plus four more. So every regressed case was still shown the file it used to
cite and stopped citing it:

| case | primary | expected paths | context files | citations |
|---|---|---|---|---|
| where-arena-aggregation | 1.00 → 0.50 | 2 | 9 → 13 | 4 → 5 |
| where-command-created | 1.00 → 0.50 | 2 | 9 → 13 | 4 → 2 |
| where-events-stored | 1.00 → 0.50 | 2 | 10 → 14 | 5 → 5 |
| where-generated-code-service | 1.00 → 0.00 | 1 | 6 → 8 | 6 → 6 |
| where-prompt-templates | 0.50 → 0.00 | 2 | 6 → 8 | 4 → 6 |

Nothing was taken away from these cases. More material made the generator *worse* at naming the
material that mattered. That is dilution in its cleanest observable form.

### The bottleneck has moved — this is the finding that should drive what comes next

Loss budget, champion vs H32-A:

| loss | champion | H32-A |
|---|---|---|
| pool depth (34) | 0.117 | 0.117 |
| rerank cut | 0.078 (34→10) | **0.018** (34→14) |
| **generation / citation** | **0.035** | **0.055** |

Widening the cut traded 0.060 of cut loss for 0.020 of extra dilution — a good trade, but it has
also made **generation the second-largest term and the fastest-growing one**. And the axis is close
to exhausted: at depth 34 the ceiling only rises 0.005 more from cut 14 to cut 20, while dilution
would keep growing. Depth 60 / cut 20 (ceiling 0.890) buys +0.025 of ceiling against a dilution cost
that is now demonstrably ~1/3 of any ceiling gain. **The deferred depth-60 arm is no longer
attractive and should not be run as designed.**

The next hypothesis belongs on conversion, not retrieval. The concrete anomaly to attack: context
grew 8.67 → 12.23 files (+41%) while `citation_count` grew only 4.22 → 4.60 (+9%). The generator is
not citing proportionally to what it is shown, and 5 cases actively forgot files they had cited with
less material in front of them.

### Prediction scoring (Finding 52's six)

1. **RIGHT on the value, WRONG on significance.** Predicted [0.79, 0.83] point 0.815 → actual 0.810.
   But I also predicted "the paired CI against the champion excluding zero", and it does not. I
   estimated the effect well and the power badly.
2. **RIGHT.** Predicted [0.76, 0.81] point 0.785 → actual 0.780.
3. **RIGHT.** Conversion fell by ≤0.04 as predicted: cl160 −0.020, cl96 −0.024.
4. **RIGHT**, including the direction — the guardrail fell rather than rose, on both arms.
5. **RIGHT.** H32-A +29.6% (predicted +20–30%), H32-B +5.4% (predicted ±8%).
6. **RIGHT on direction, short on magnitude.** 4.22 → 4.60/4.67; I said "toward ~5".

Five and a half of six, against two-of-five on each of the last two findings. The difference is that
Findings 49 and 51 asked me to predict *how a model behaves given more or less material* and this
one mostly asked me to predict *what a validated instrument would report*. The one miss here is the
same class as before: a claim about statistical power, dressed as a claim about the effect.

---

## Finding 54 (pre-registered) — H34: the six retrieval knobs nobody has ever measured

Finding 53 left pool depth as the largest loss in the pipeline: **0.117**, against 0.055 for
generation and 0.018 for the rerank cut. The pool is produced by seven numbers in
`graph_file_search`, and Finding 22 swept exactly one of them (`graph_weight`, found to sit on a
cliff edge at 0.45). Grepping the whole log: `vector_weight`, `lexical_weight`, `path_weight`,
`symbol_weight`, `lexical_seed_limit` and `min_token_length` appear **zero times**, and `seed_limit`
once in passing. They are the values the config was born with. Six untested knobs sitting on the
biggest loss term is the largest unexamined surface left in the project.

### Instrument

`scripts/replay_weight_grid.py` — new. Replays the persisted probe queries through the real
`graph_file` strategy, rebuilding it once per grid point with only the swept fields overridden;
embedding provider, vector store and graph are shared across points, so a row difference is the
weights and nothing else. Reports MACRO recall (the pipeline convention) with micro alongside.

**Override reach verified before use**, because Finding 35 was exactly the bug of a config override
that never arrived. On a 6-case subset: champion pool@34 = 0.9167; zeroing all four non-graph
weights collapses it to **0.0000**; `graph_weight: 0` drops it to 0.7500; `seed_limit: 20` drops it
to 0.7500. The overrides land.

Cost: ~1.6 s/case steady state, no generation, no judge. The 13-point grid is ~35 min of CPU
against ~16 hours of live arms.

### Design

One-at-a-time around the champion (vector 0.25 / lexical 0.25 / path 0.20 / symbol 0.10 / graph 0.45,
seeds 140/280), 13 points. OAT rather than factorial because nothing yet says these factors interact
and a 4-factor 3-level grid is 81 points; this pass asks only *which knobs move the pool at all*, and
whatever moves it earns a proper 2-D grid afterwards. `graph_weight` is excluded so no row is
confounded with Finding 22's known-sharp effect.

Screening metric is pool recall@34 macro. That is a CEILING on post-rerank recall, not a prediction
of it — Finding 51 showed the two can move in opposite directions — so finalists get re-measured with
`--rerank-cut 14`, which is the quantity that actually feeds the context builder.

### Predictions

1. **Instrument validation.** Champion pool@34 macro reproduces Finding 51's 0.883 to within 0.005.
2. **The weight region is flat.** No single OAT *weight* point moves pool@34 macro by more than
   0.010. Reasoning: `graph_weight` 0.45 dominates the fusion and Finding 22 already located the
   signal there; the other four weights only reorder within a candidate set the seeds already fixed.
3. **Seeds beat weights.** The seed-limit points move pool@34 more than any weight point, and
   `seed-200` is the largest single gain in the grid (≥ +0.005). Reasoning: `seed_limit: 20` cost
   0.167 in the sanity run, so the seed stage binds; weights cannot add a candidate that seeding
   never produced.
4. **This axis does not close the gap.** The best grid point's pool@34 macro is ≤ 0.900 — at most a
   fifth of the 0.117 loss. If this is wrong the axis is far richer than I think and deserves the
   full factorial immediately.
5. **Direction.** `lexical-0.35` > `lexical-0.15` and `path-0.30` > `path-0.10`, because every case
   in this dataset is a "where is X" question and identifier/path surface form carries the answer.
6. **Ceiling ranking will mislead.** Ranking the finalists by pool@34 will not match ranking them by
   post-rerank recall@14 — at least one inversion, per Finding 51's precedent.

Predictions 2 and 4 together say this axis is mostly closed. Registering them that way on purpose:
the cheap outcome to fake after the fact is "I expected the winner all along", and the honest test of
Finding 53's claim that retrieval is nearly exhausted is to predict a null and see if it holds.

---

## Finding 55 — H34 verdict: the retrieval weight axis is closed, and the reranker is why

13 OAT points + 6 extension points + 3 replicates + a 4-point rerank confirm, 100 cases each,
offline. Total cost ~50 min of CPU and zero GPU generation.

### Noise floor first

Three champion replicates: pool@34 **0.8833** three times, pool@10 **0.6650** three times, pool@14
0.7600 / 0.7600 / 0.7550. So the pool noise floor is **0.000 at depth 34 and at k=10**, and 0.005 at
k=14. Finding 51a already put the post-rerank floor at 0.000. Every number below is read against
those floors.

### The grid

| point | pool@10 | pool@14 | pool@34 | Δ@34 |
|---|---|---|---|---|
| lexseed-200 | 0.6750 | 0.7550 | **0.8933** | +0.0100 |
| vector-0.45 | 0.7200 | 0.7750 | 0.8883 | +0.0050 |
| vector-0.35 | 0.7250 | 0.7750 | 0.8833 | 0.0000 |
| **champion** | 0.6650 | 0.7600 | 0.8833 | — |
| symbol 0.0 / 0.05 / 0.20 / 1.0 | 0.6650 | 0.7600 | 0.8833 | 0.0000 |
| vector-0.60 | 0.7200 | 0.7750 | 0.8683 | −0.0150 |
| minlen-2 | 0.6550 | 0.7500 | 0.8633 | −0.0200 |
| lexical-0.15 | 0.6500 | 0.7250 | 0.8483 | −0.0350 |
| path-0.10 | 0.6500 | 0.7350 | 0.8433 | −0.0400 |
| vector-0.15 | 0.6150 | 0.7000 | 0.8183 | −0.0650 |

Every downward move on vector/lexical/path hurts; no upward move helps by more than 0.010. The
champion sits on or immediately beside a local optimum on all four weights — a config that was never
tuned landed within 0.010 of the best point reachable on this axis.

`vector-0.35 + lexseed-200` = 0.8833: the combination **loses** the lexseed gain instead of adding
it. The factors are not additive, so the OAT design cannot be extrapolated to combinations. Anything
further on this axis would need a real factorial, and Finding 55's conclusion is that it would not
be worth running.

### The rerank confirm kills all of it

| point | pool@34 | Δ pool | rerank@14 | Δ rerank |
|---|---|---|---|---|
| champion | 0.8833 | — | **0.8650** | — |
| lexseed-200 | 0.8933 | +0.0100 | 0.8650 | **0.0000** |
| vector-0.35 | 0.8833 | 0.0000 | 0.8600 | −0.0050 |
| vector-0.45 | 0.8883 | +0.0050 | 0.8600 | −0.0050 |

The champion's 0.8650 reproduces the live H32-A `candidate_file_recall` of 0.8650 exactly — the third
independent end-to-end validation of the replay instruments.

**The best ceiling gain in the entire grid converts to exactly zero primary.** `vector-0.45` is the
sharpest case: a higher ceiling (+0.0050) *and* a large pool@10 gain (+0.0550), and it lands 0.005
*worse* after reranking.

**Mechanism.** `cross_encoder_rerank.preserve_top_candidate: false` — the cross-encoder rescores all
34 candidates from scratch, so pool *ordering* is thrown away entirely and only pool *composition*
can matter. The weights are a reweighting of an already-fixed seed set, so they mostly reorder. This
is the same reranker-as-equalizer effect Finding 32 called a capacity ceiling, seen from the other
side: the reranker absorbs upstream ranking work, which is why upstream ranking work does not pay.

**Verdict: the fusion-weight and seed-limit axis is closed.** No live arm is warranted.

### `symbol_weight` is inert, and its input was never indexed

0.0, 0.05, 0.10, 0.20 and 1.0 give byte-identical pools at every k. Cause: `symbol_weight` scales
`symbol_score`, which derives from `metadata_terms` — built in `hybrid_item_profiler.py:18-30` from
`kind`, `symbol`, `source`, `index_kind`. **0 of 8222 indexed items carry a `symbol` field**; the
available keys are `doc_role`, `doc_title`, `index_kind`, `kind`, `source`. So the score is
0-or-constant across candidates and any weight shifts all totals equally.

The knob is not broken — it is fed nothing. That is the interesting part: `lexical_weight` and
`path_weight` are the two largest movers in the grid (−0.035 and −0.040 when halved), so surface-form
identifier matching demonstrably carries signal on "where is X" questions, while the one signal aimed
squarely at identifiers receives no input. A per-file symbol list is lean metadata of exactly the
kind this index is designed to hold. **That makes it a hypothesis about the index, not the
retriever** — and the index is the one layer this whole 55-finding series has never touched.

### Prediction scoring — 4 of 6

1. **RIGHT.** Champion pool@34 = 0.8833 vs Finding 51's 0.883.
2. **WRONG.** I said no weight point would move pool@34 by more than 0.010; `vector-0.15` moved it
   0.065, six times my bound. I read "graph_weight dominates the fusion" as "the other weights are
   nearly inert", and that does not follow — a dominant term can still leave the others load-bearing.
3. **WRONG, both halves.** I said seeds would beat weights and that `seed-200` would be the largest
   gain. Weights beat seeds by 6×, and `seed-200` was negative (−0.0100).
4. **RIGHT.** Best point 0.8933, under the 0.900 line.
5. **RIGHT.** `lexical-0.35` > `lexical-0.15` and `path-0.30` > `path-0.10`.
6. **RIGHT.** The ceiling ranking inverted against the post-rerank ranking: `vector-0.45` was 2nd by
   pool and last by rerank; the champion was last by pool and first by rerank.

The two misses are both about *magnitude within the retrieval stage*, while the four hits are about
*the stage's total contribution*. I predicted the system-level outcome correctly (predictions 4 and 6
carried the verdict) and the internal mechanics badly — the opposite of the H32 pattern, where I had
the effect right and the power wrong. Worth watching whether that alternation is a real weakness or
noise across six-prediction batches.

---

## Finding 56 (pre-registered) — H33: does breaking up the directory clusters cost retrieval?

The H33 diagnosis (recorded on task #28) found the 5 H32-A regressions share one mechanism: in
every case the generator swapped the expected file for a same-directory sibling that arrived with
the four extra files at cut 14. Citation counts across the five went 4→5, 4→2, 5→5, 6→6, 4→6 — a
roughly fixed 4–6 budget that does not scale with context, matching the aggregate signature
(context +41%, citations +9%). A cross-encoder scores same-cluster files alike, so the extra slots
fill with near-duplicates and the budget goes to cluster-internal consistency instead of the lone
cross-cluster file that was the answer.

### What this instrument can and cannot decide

`scripts/replay_context_diversity.py` — new. One rerank call per case to a depth-34 ordering, then
five selection policies evaluated against that same ordering for free (prefix stability, validated
in Finding 51). Policies: `plain` (shipped), `dircap-2/3/4` (no directory contributes more than N,
with backfill so the window is never short), `round-robin` (every directory gets a first slot before
any gets a second).

This measures **retrieval**. Whether de-clustering makes the generator cite better is a
**generation** question that no offline replay can answer — it needs a live arm. The purpose here is
to kill the idea for five minutes of CPU if diversity costs recall, and to size the arm if it does
not. Saying so before running, because the tempting move afterwards is to present a retrieval number
as if it settled the conversion question, and it cannot.

`max_directory_share` (mean over cases of the largest directory's share of the window) is the
quantity the diagnosis actually indicts — `where-generated-code-service` showed six of eight files
from one directory. A policy that does not move this number is not testing the hypothesis whatever
it does to recall.

### Predictions

1. **Harness validation.** `plain` at k=14 reproduces 0.8650, the value now confirmed three
   independent times (live H32-A, Finding 51 grid, Finding 55 confirm).
2. **`plain` is cluster-heavy.** Baseline `max_directory_share` ≥ 0.40 — i.e. on average more than
   two of every five shown files come from a single directory. If this is below 0.30 the diagnosis
   was built on five unrepresentative cases and H33 should be dropped.
3. **Mild caps are nearly free.** `dircap-4` costs ≤ 0.005 recall (within the 0.005 jitter seen at
   k=14 in Finding 55). Reasoning: a cap only binds on cases already dominated by one directory, and
   the backfill returns the skipped files whenever the cap starves the window.
4. **Aggressive diversity costs real recall.** `round-robin` loses ≥ 0.020, because expected files
   frequently cluster *together* — `where-arena-aggregation` expects two files from `src/arena/`, and
   forcing one-per-directory pushes the second out of the window.
5. **`dircap-3` is the knee.** It moves `max_directory_share` by ≥ 0.10 while costing ≤ 0.010 recall,
   and is the policy that goes to a live arm.
6. **Bundle-completeness moves more than recall.** Whatever the caps do to macro recall, they change
   `bundle_complete` by a larger absolute amount, because the cap's whole effect is on cases whose
   expected set spans directories — which is exactly the population bundle-completeness scores.

Prediction 4 is the one I most expect to be embarrassed by. Findings 51 and 55 both punished me for
assuming a stage behaves the way its mechanism suggests, and "expected files cluster together" is
that same kind of reasoning. If `round-robin` turns out free, the cut has far more slack than I think
and the useful policy is the aggressive one.

---

## Finding 57 — H33 as a retrieval fix is refuted: the clustering is signal, not noise

100 cases, pool 34, window k=14, offline.

| policy | recall | Δ | bundle | mean_dirs | max_dir_share |
|---|---|---|---|---|---|
| **plain** (shipped) | **0.8650** | — | 0.790 | 7.59 | 0.360 |
| dircap-4 | 0.8050 | −0.0600 | 0.710 | 8.32 | 0.269 |
| dircap-3 | 0.7600 | −0.1050 | 0.640 | 9.01 | 0.217 |
| dircap-2 | 0.6933 | −0.1717 | 0.560 | 10.19 | 0.152 |
| round-robin | 0.5883 | −0.2767 | 0.440 | 13.10 | 0.101 |

`plain` reproduces 0.8650 for the fourth independent time.

**Every diversity policy is strongly negative, and monotonically so.** The exchange rate between
directory concentration removed and recall lost is 0.66 at `dircap-4` and rises to 1.07 at
`round-robin` — push hard enough and you lose a point of recall for every point of concentration you
remove. The cross-encoder's same-directory clustering is *informative*: when it ranks four files
from one directory highly, those files are frequently the expected ones. Replacing any of them with
a lower-ranked file from elsewhere costs more than it buys, at every setting tested.

### The reframing from the H33 diagnosis was wrong, and the measurement says why

Task #28 concluded, from the 5 H32-A regressions, that "this is a retrieval-layer problem, not a
prompt problem" and that a prompt fix should be the fallback rather than the first arm. **That is
now refuted.** The retrieval layer is doing the right thing; the original guess — a generation-side
citation-budget problem — was correct.

The early warning was in prediction 2, which I got wrong in the informative direction: I predicted
baseline `max_directory_share` ≥ 0.40 and pre-registered that a value below 0.30 would mean the
diagnosis rested on unrepresentative cases. It came in at 0.360 with `mean_directories` = 7.59 —
the shipped 14-file window already spans seven-plus directories. It was never cluster-dominated in
aggregate. **I generalized from five hand-picked regressions to a hundred-case corpus**, and the
aggregate did not share the property those five had.

### Where H33 actually goes

`answer_evaluator.py:391-413` builds the answer prompt. It says *"Cite relative file paths and line
numbers from the context for important claims"* and contains **no coverage instruction at all** —
nothing states the answer may span multiple files, nothing asks the model to consider each shown
file, nothing sets an expected citation count. The model picks what it deems "important" and settles
on 4–6 regardless of whether it was shown 9 files or 14.

That is the intervention: a coverage clause, tested against the shipped prompt as a live pair. It
cannot be screened offline — the whole quantity of interest is what the generator chooses to cite.

### Prediction scoring — 3 of 6

1. **RIGHT.** `plain` = 0.8650.
2. **WRONG.** Predicted `max_directory_share` ≥ 0.40, actual 0.360 — and I had pre-registered that
   this exact shortfall would indict the diagnosis. It did.
3. **WRONG, by 12×.** Predicted `dircap-4` costs ≤ 0.005; it cost 0.060. I assumed the cap "only
   binds on cases already dominated by one directory". With `mean_directories` at 7.59 and a
   34-deep pool to backfill from, the cap binds nearly everywhere.
4. **RIGHT.** `round-robin` lost ≥ 0.020 — it lost 0.277.
5. **WRONG.** No knee exists. `dircap-3` moved concentration by 0.143 as predicted but cost 0.105
   recall, not ≤ 0.010. The curve is monotone with no free region.
6. **RIGHT.** `bundle_complete` moved more than recall at every policy (−0.080 vs −0.060 at
   `dircap-4`, −0.350 vs −0.277 at `round-robin`).

I flagged prediction 4 in advance as the one I most expected to be embarrassed by. It was the one
that held. The three misses were all the same error in different clothes: reasoning from the
mechanism of five cases to the behaviour of a hundred, without checking whether the aggregate had
the property. Findings 51 and 55 punished the same habit. Three findings in a row is not noise — the
rule to adopt is that a mechanism found in hand-picked failures must have its prevalence measured on
the full corpus **before** it becomes the basis of an intervention.

---

## Finding 58 — H32-A cannot be resolved by rerunning it, and the empirical null says why

The question left open by Finding 53 was whether H32-A's 13 up / 5 down / 82 ties is a real effect
or noise. Finding 35 already contained the answer material and nobody had extracted it.

### The empirical null

The h17-ctrl / h25 pair is an accidental **same-config re-run** (h25 differed only in a field the
eval path ignored). Paired case by case on the primary:

| | up | down | ties | discordant | sign p |
|---|---|---|---|---|---|
| **null** (same config, twice) | 4 | 5 | 91 | 9 | 1.0000 |
| **H32-A vs champion** | 13 | 5 | 82 | 18 | 0.0963 |

Two things follow.

**The sign test's symmetric-null assumption is validated empirically.** Pure pipeline
nondeterminism produces 4 up / 5 down — as close to symmetric as nine cases can be. The test was
the right test.

**H32-A doubles the discordance rate**: 18/100 against a null of 9/100, Fisher two-sided
**p=0.0965**. Note that this lands at essentially the same p as the sign test, and the two are *not*
independent — the same 18 cases drive both — so they cannot be combined. This is a second view of
one body of evidence, not a second body of evidence.

Caveat on the null: it was measured on the pre-cross-encoder pipeline (LLM rerank, primary 0.715).
Today's cross-encoder is deterministic (Finding 39), so 9/100 is probably an **upper bound** on the
current null, which if anything strengthens H32-A. I am not going to claim the strengthening
quantitatively without measuring it.

### More runs cannot fix this. Only more cases can.

Paired on the primary: delta **+0.0400**, sd **0.2429**, SE **0.0243**, CI **[−0.0076, +0.0876]**.
The variance is case-level, not run-level, so averaging additional runs of the same 100 cases
shrinks the run-noise component and leaves the dominant term untouched.

- **142 cases** would make the CI exclude zero at the observed effect size.
- **289 cases** would give 80% power at two-sided 0.05.

The dataset has 100. **This is the finding that should govern planning**: the project has reached
the point where its measuring instrument, not its pipeline, is the binding constraint. Every arm
from here that produces an effect of ~0.04 will land in exactly this position, and the next three
hypotheses on the board (H33 coverage clause, H35 symbol index, prefill) are all plausibly in that
range. 42 more cases is a small, well-defined piece of work with a larger return than any of them.

### Status of H32-A

Against the pre-registered H16 rule ("rank on the primary; it must not fall"), H32-A qualifies: the
primary rises to 0.810, the best recorded; the guardrail *improves* 0.031 → 0.020; the mechanism is
proven independently (`candidate_file_recall` +0.060 [0.028, 0.092], `candidate_bundle_complete`
9 up / 0 down, p=0.0039). What it lacks is a resolvable primary, at p≈0.10 twice over.

What it also carries is **+29.6% latency**, and that is not a detail on a project whose stated goal
is a latency/quality optimum. H32-A buys +5.2% relative primary for +29.6% wall clock. Whether that
is a good trade is a product decision, not a statistical one, and it should be recorded as a
**frontier** rather than settled by crowning one config:

| point | primary | guardrail | s/case | position |
|---|---|---|---|---|
| h30 cl96/cut10 | 0.745 | 0.028 | 39.5 | fastest |
| **h29 champion** cl160/cut10 | 0.770 | 0.031 | 44.8 | balanced, incumbent |
| H32-B cl96/cut14 | 0.780 | 0.024 | 47.3 | +1.3% quality for +5.4% latency |
| **H32-A** cl160/cut14 | **0.810** | **0.020** | 58.1 | quality-first, +29.6% latency |

Note H32-B against the incumbent: +0.010 primary and a better guardrail for +5.4% latency. Its
primary delta is well inside noise, but it is the only arm on the board whose latency cost is small
enough that adopting it on the guardrail alone would be defensible.

---

## Finding 59 — the corpus, not the pipeline: 100 → 247 cases

Finding 58 ended with the conclusion that the measuring instrument is the binding constraint:
the h29-champion vs H32-A comparison sits at +0.0400 primary, sd 0.2429, SE 0.0243,
CI [−0.0076, +0.0876], sign p=0.0963, and **the variance is case-level**, so re-running the same
100 cases cannot move it. 142 cases would make the CI exclude zero at the observed effect;
289 would give 80% power at two-sided 0.05.

### What was built

`datasets/protogen_eval_247.jsonl` and `datasets/protogen_answer_cases_247.jsonl`.
The original 100 records are a **byte-identical prefix** (verified record-by-record against
`protogen_answer_cases_100.jsonl`), so every prior report remains a valid subset and `--cases 100`
reproduces the old corpus exactly. 147 new cases follow.

Provenance of the new cases: an AST inventory of every `src/**.py` in `../protogen` over 40 LOC,
excluding tests, `__init__.py`, and any file already named by one of the original 100 — 270
candidates. Questions were authored from module docstrings and public API, in the corpus's own
behavioural style (`where is X done`), never naming the target file.

### Validation performed before freezing

- **All 327 distinct expected paths exist on disk.** Zero missing.
- **All 327 are in the index** (3842 indexed files in the file-graph catalog). No case has a
  structurally unreachable answer, in either the old or the new half.
- **No id collisions**, no duplicate ids, no expected path reused from an original case.
- **Near-duplicate screen**: line-level `SequenceMatcher` over same-basename files repo-wide found
  no unlisted twin of any target. (A first pass using `quick_ratio` flagged everything and was
  discarded — it is a bag-of-characters upper bound, useless for source files.)
- **Competitor screen**: keyword overlap between each question and every file's path+docstring,
  flagging any unlisted file scoring at least as high as the listed one. 72/150 drafts flagged,
  most spuriously (`__init__.py`, test files). The real ones were repaired:
  - **3 drafts dropped** for colliding with existing ground truth — `where-cross-feature-pm`
    (vs `where-product-manager` → `product_manager/agent.py`), `where-platform-load`
    (vs `where-platform-module` → `platform/registry.py`), `where-lead-product-owner`
    (folded into one product-owner case covering both agents).
  - **14 drafts widened** to include a genuinely co-owning file, following the convention the
    original 100 already use (`where-command-created` → `commands_click/generate.py` +
    `commands/generate.py`). The CLI has two parallel command trees, so
    monitor/metrics/session/server commands are pairs; the four external-coder cases pair the
    `codegen/*_wrapper.py` with its `operators/*` counterpart; `where-team-config-validated`
    picks up `yaml_validator.py`; `where-post-generation-wiring` picks up `consolidation_op.py`.

  Without these repairs a correct retrieval would have scored as a miss. This screen is the
  Finding 57 rule applied to labelling: measure prevalence before acting on a mechanism.

Expected-set sizes: 153 singles / 92 pairs / 2 triples (the original was 38/61/1; the new half is
115/31/1). The singles skew was considered and accepted. Single-expected cases have larger per-case
delta variance (|d|=1 when discordant rather than 0.5), but the effect scales with it — power per
case is governed by effect/sd, and both numerator and denominator double. Forcing pairs by inventing
conjunctive questions would have raised n while degrading label quality, which is the wrong trade
for a corpus whose whole purpose is to be a better instrument.

### Why 247 and not 289

147 defensible labels were available from genuinely uncovered subsystems. 247 clears the 142 mark
at which the CI excludes zero for the observed effect and reaches ~72% of the 289-case 80%-power
target. Padding to 289 would have meant authoring 42 more cases over ground already covered or over
files whose ownership is ambiguous — buying nominal n by adding noise. Record this as a known
limitation: **at 247, a null result on H32-A is not evidence of no effect.**

### Smoke test (6 new cases, cut 10, champion config)

0 errors, `citation_expected_recall` 0.6667, `candidate_file_recall` 0.7500,
`citation_fabricated_rate` 0.0000, `citation_line_valid_rate` 1.0000, 48.8 s/case.
The new cases are discriminative rather than trivial — `where-agent-dependencies` is a clean miss
(the answer cited `agents/base/models.py`, `base/__init__.py`, `base.py` and never reached
`agents/dependencies.py`). Note 48.8 s/case against the 44.8 recorded for this arm on the old
corpus: Finding 37 again — compare shares, not seconds.

### Re-run in flight

`/tmp/dsx/run_247_arms.sh`, sequential (latency is measured; both arms share the GPU servers),
same config and flags as the 100-case runs with only `--limit`/`--context-files` differing:

- `protogen-h29-xenc-strict-cite-247-cf10-cl160` — champion, cut 10, started 2026-08-11 14:50
- `protogen-h32-cut14-247-cf14-cl160` — H32-A, cut 14

Both clobber-guarded on `.json` and `.partial.json`. H32-B (cl96/cut14) is deliberately not in this
batch — it can be re-run once the primary question is settled, and running three arms would triple
the window in which no other GPU work can happen.

---

## Finding 60 — H32-A is refuted on the primary. The corpus expansion paid for itself immediately.

Both arms completed on the 247-case corpus, 0 errors each. Champion cut 10: 3:06:23, 45.3 s/case.
H32-A cut 14: 3:50:31, 56.0 s/case (+23.7%).

### The primary does not move

| slice | n | champion | H32-A | paired delta | CI95 | up/down/tie | sign p |
|---|---|---|---|---|---|---|---|
| **all 247** | 247 | 0.8171 | 0.8333 | **+0.0162** | [−0.0055, +0.0379] | 15/9/223 | 0.3075 |
| original 100 | 100 | 0.7650 | 0.8000 | +0.0350 | [−0.0074, +0.0774] | 11/5/84 | 0.2101 |
| **new 147** | 147 | 0.8526 | 0.8560 | **+0.0034** | [−0.0188, +0.0256] | 4/4/139 | 1.0000 |

The original 100 replicated: +0.0350 here against +0.0400 in Finding 53, 16 discordant against 18.
Run-to-run drift of ~0.005 on each arm, consistent with Finding 50a. Nothing was broken.

**On 147 cases this experiment had never seen, the effect is +0.0034 with 4 up and 4 down.** That is
not a smaller effect, it is no effect. Pooled, the arm now needs n=443 for the CI to exclude zero and
n=905 for 80% power — i.e. the thing Finding 58 was sizing for was largely an artefact of the 100
cases it was sized on.

Checked whether the shrinkage is a corpus-half artefact rather than a real refutation, by splitting
on expected-set size across both halves (the new half is 78% single-expected, the old half 38%):

| slice | n | delta | up/down |
|---|---|---|---|
| singles, old-100 | 38 | +0.0263 | 1/0 |
| singles, new-147 | 115 | +0.0087 | 1/0 |
| multi-file, old-100 | 62 | +0.0403 | 10/5 |
| **multi-file, new-147** | 32 | **−0.0156** | 3/4 |

Every subgroup's CI covers zero, and the multi-file cases — where a wider cut has the most room to
help — go *negative* on fresh data. The composition difference between the halves does not rescue
the effect. H32-A does not beat the champion on `citation_expected_recall`.

### What is real, and it is the whole story

The retrieval mechanism replicates cleanly and one-sidedly on both halves:

| metric | all 247 | old 100 | new 147 |
|---|---|---|---|
| `candidate_file_recall` | **+0.0344** [+0.0176, +0.0512], 16u/0d, p<0.0001 | +0.0600, 12u/0d | +0.0170, 4u/0d |
| `candidate_bundle_complete` | **+0.0526** [+0.0247, +0.0805], 13u/0d, p=0.0002 | +0.0900, 9u/0d | +0.0272, 4u/0d |
| `citation_count` | **+0.6437** [+0.4009, +0.8866], 124u/49d | +0.5200 | +0.7279 |
| `citation_fabricated_rate` | −0.0004, 19u/18d, p=1.0000 | −0.0005 | −0.0003 |

Zero cases got *worse* retrieval — as expected, cut 14 is a superset of cut 10. The generator also
demonstrably notices, citing 0.64 more files per answer. The guardrail is flat, so nothing was traded
away. And yet the primary is flat too.

**The conversion rate is the finding.** +0.0344 more expected files delivered into context yields
+0.0162 primary — under half converts. On the fresh half it is +0.0170 → +0.0034, roughly 20%. The
generator is handed more of the right files, writes more citations, and does not spend the extra
citations on the files that were added.

### Decision

**Do not promote H32-A.** The champion stays at cut 10. Paying +23.7% latency for a primary delta
whose CI covers zero on 247 cases, and which is +0.0034 on the cases that were not used to discover
it, is not a trade the stated latency/quality goal supports. Task #27 is closed as refuted-on-primary
with its mechanism confirmed.

The frontier table in Finding 58 should be read with cut-14's quality column struck out. What remains
of that table is h30 cl96/cut10 and the h29 champion, plus H32-B which was never re-measured here.

### What this redirects

Task #28 (H33) is now the only live lead and it is better motivated than before: retrieval has been
proven to deliver files the generator will not cite, on 247 cases, one-sidedly, with a flat guardrail.
Finding 57 already killed the diversity framing offline. The untested intervention is the coverage
clause in `answer_evaluator.py:391-413` — the prompt currently never tells the model that an answer
may span several files, nor asks it to consider each file it was shown.

### Methodological note

This is the first time a promising arm has been killed by data it was not tuned on. The corpus
expansion cost roughly one afternoon of labelling and 7 hours of GPU, and it prevented adopting a
+23.7% latency regression for nothing. Standing rule, to sit beside Finding 57's: **an effect
discovered on a corpus must be confirmed on cases added after it was discovered before it is
promoted.** Held-out data, not more runs, is what separates a finding from a coincidence.
