# H36 — raise the rerank pool depth, then prove it on repositories we never tuned on

Date: 2026-08-12
Champion at start: `configs/context-awareness/protogen-h29-xenc-strict-cite.yml`
(0.8171 `citation_expected_recall`, 45.2 s/case, protogen 247 cases)

## Why

The loss chain, measured on protogen 247 (Finding 61):

```
0.980   retrieval can reach this at pool depth 200
  ↓ −0.091   we cut the pool at candidate_limit 34
0.889   what the cross-encoder is allowed to see
  ↓ −0.054   cross-encoder keeps the top 10
0.835   what the generator is shown
  ↓ −0.018   generator declines to cite
0.817   primary
```

The pool cut is the largest single loss and rerank costs only 2.06 s of 45.2 s (4.6%),
so depth is the cheapest axis left. Generation-side work is capped at +0.018 and is
therefore closed (task #28).

## Pre-registered

* Primary: `citation_expected_recall`, matched-pair against the existing champion report
  `.code-diver/reports/protogen-h29-xenc-strict-cite-247-cf10-cl160.json`.
* Anti-gaming guardrail: `citation_expected_precision`, baseline **0.3675**. A deeper pool
  must not buy recall by making the model cite more files. Reject if precision falls below
  0.33 while recall rises — that is the signature of shotgun citation, not better retrieval.
* Fabrication guardrail: `citation_fabricated_rate`, baseline 0.0268, bound 0.035.
* Latency: rerank is linear in candidates, so depth 100 should cost ≈ +4 s (+9%). Reject
  above +15% unless the primary gain clears +0.03.

Prediction before the screen: pool recall rises 0.889 → 0.950 at depth 100, and the
cross-encoder converts **part** of it. If conversion holds at the depth-34 rate (94%) the
shown-recall goes 0.835 → 0.89. If the extra 66 candidates are mostly distractors, it stays
flat. Both outcomes are informative; flat kills depth and promotes #30 (symbol index).

## Step 1 — offline screen (running)

`scripts/replay_rerank_depth.py` over the 247 corpus, depths 34/60/100 × cuts 10/14.
No generation, ~2.4 s/case/depth. Picks the depth; nothing is promoted on replay alone.

## Step 2 — live arm on protogen

One new arm at the chosen depth, cut 10, matched against the champion report already on
disk. ~3.5 h. Clobber-guard the output and its `.partial` sibling.

## Step 3 — external validation (the part that actually matters)

Every number to date comes from **one repository**. The 0.817 has no demonstrated
generalization. Three assets are already on disk and need no re-indexing:

| corpus | cases | store | graph catalog | embedding |
|---|---|---|---|---|
| protogen | 247 answer | qdrant `code_diver_h17_ctrl` | `protogen-h17-ctrl.file-graph-catalog.json` | Qwen3-Embedding-0.6B |
| IntelliJ Community | 1000 | qdrant `intellij_community_file_manifest_local_qwen` (149 812 pts) | `intellij-postrank-h3-manifest-graph.file-graph-catalog.json` (383 MB) | same |
| CodeSearchNet Python (MTEB) | 1000 | json `index-h10-graph-file-qwen3-0_6b-quality.json` | `graph-h10-graph-file-qwen3-0_6b-quality.file-graph-catalog.json` | same |

All three share the champion's embedding model, so the champion's search strategy ports
without a re-index. Validated 2026-08-12: all 675 IntelliJ expected paths still exist in the
current checkout (`8f2bb3197f0f`), 0 unanswerable cases.

Run the **search axis** on IntelliJ and CodeSearchNet — file recall, no generation. That is
both the cheap axis and the exact axis a pool-depth change moves. Run each at the old depth
and the new one, so external corpora get the same matched-pair treatment protogen gets.

Only if the search axis holds does the answer axis on `intellij_eval_1000.answer_sets.jsonl`
become worth its GPU time.

## Rules for this batch

* Serial. Latency is a measured quantity (Finding 37) and all arms share the same servers.
* Clobber-guard every output including `.partial` siblings.
* No source edits while an arm is in flight.
* Finding 60's standing rule applies: an effect discovered on protogen is not promoted until
  it survives on a corpus that did not produce it. IntelliJ and CodeSearchNet are that corpus.

---

## Result — H36 REFUTED (2026-08-12)

The offline screen ran the real cross-encoder over the real merged pool at three
depths, 247 cases, cuts 10 and 14:

| pool depth | pool recall | bundle | reranked @10 | bundle | reranked @14 | bundle | rerank s/case |
|---|---|---|---|---|---|---|---|
| 34 (shipped) | 0.883 | 0.866 | **0.808** | 0.781 | 0.851 | 0.830 | 1.90 |
| 60 | 0.921 | 0.907 | 0.796 | 0.769 | 0.857 | 0.830 | 3.16 |
| 100 | 0.953 | 0.943 | **0.784** | 0.749 | 0.845 | 0.830 | 5.23 |

The pool behaves exactly as predicted — 0.883 → 0.953, the extra candidates really
do contain the missing files. The cross-encoder does not: conversion of pool recall
into top-10 recall falls **91.5% → 86.4% → 82.3%**. Depth 100 costs +3.3 s/case and
loses 0.024 recall. No live arm is warranted; nothing is promoted.

### What this actually says

The −0.091 I attributed to "the pool cut" in Finding 61 is not a supply problem. Cutting
at 34 discards 0.070 of reachable recall, but handing those same candidates to the
cross-encoder does not recover them — it loses more than it gains, because each added
distractor competes for the same ten slots and the model ranks some of them above the
true positive. The pool cut and the rerank cut are not two stacked losses that can be
attacked separately; the second one *absorbs* the first.

So the binding constraint is **cross-encoder ranking quality at fixed width**, not
candidate supply. Every remaining retrieval-side lever must improve the ordering, not
the pool:

* better candidate *representation* (task #30, per-file symbol lists — the one layer
  never indexed; a manifest that names the symbols gives the cross-encoder something to
  match a "where is X" question against)
* a second ranking stage over a small survivor set (task #18) — note this is now
  motivated differently: not to fit more candidates through, but to give the top ~20 a
  pairwise comparison the single-pass scorer never makes
* query-side precision: better probes retrieve fewer distractors in the first place

Cut 14 remains the only width that moves shown-recall (+0.043 at depth 34), and
Finding 60 already refuted it end-to-end on held-out cases — it buys shown-recall and
gives it back at the citation step (cite-if-shown 0.9729 → 0.9511). Not revisited.

### Standing note on the replay/live offset

Replay recall@10 at the shipped depth is 0.808; the live arm measures 0.8354 shown-recall
(Finding 50a). Treat replay numbers as *comparative only*. The ~0.027 gap is stable across
depths here, which is why the ranking of the three depths is trustworthy even though the
absolute values are not.

---

## H37 — external validation, and the reason it could not start (2026-08-12)

### Finding 63: `graph_file_cross_encoder` has never had a graph on any JVM repository

The champion's largest single scoring weight is `graph_file_search.graph_weight: 0.45`. It
runs on file->file adjacency derived from the graph artifact's cross-file edges. Measured:

| corpus | items | edges | kinds | file adjacency |
|---|---|---|---|---|
| protogen | 8 843 | 17 364 | imports 5 644, summarizes 5 622, references 4 401, same_file_next 1 697 | 1 911 files |
| IntelliJ (June artifact) | 149 812 | 74 906 | summarizes 74 906 | **0 — empty** |
| CodeSearchNet | 2 000 | 1 000 | summarizes 1 000 | **0 — empty** |

Both externals held exactly one intra-file `summarizes` edge per file, so the file-level
adjacency map was literally `{}` and the 0.45 term scored zero on every candidate.

Root cause, and it is not the config: `CodeGraphBuilder._imports_for_file` dispatched on
suffix and handled `.py` and `.ts/.tsx/.js/.jsx` only -- everything else fell through to
`return set()`. IntelliJ is 39 308 `.java` + 31 986 `.kt` = 95% of the repository. The second
mechanism reinforces it: `_reference_edges` keys off `_symbol_name`, which returns `""` for
`file_summary`/`file_manifest`, the only kinds a manifest index contains. So
`reference_edges_enabled: true` would also have produced nothing.

This is why the IntelliJ config carries `expansion_depth: 0, neighbor_limit: 0` -- someone
correctly observed the graph did nothing and turned it off, rather than asking why.

### The fix

`_jvm_imports` + `_jvm_class_index` in `code_graph_builder.py`. Resolution runs backwards:
a JVM import names a package and the source root (`platform/util/src/` before
`com/intellij/util/`) is not recoverable from the layout, so index by simple class name and
keep candidates whose path tail matches the imported package. Static member imports and
nested classes walk capitalised segments right-to-left to the enclosing top-level file;
wildcards name no class and are skipped rather than expanded to a package.

`IMPORT_TARGETS_PER_FILE = 64` is new and bounds the monorepo tail. Protogen's heaviest file
resolves 31 in-repo imports, so the cap cannot retroactively alter the champion.

Correctness gate before spending on the monorepo: `scripts/build_graph_artifact.py`
reproduced the shipped protogen artifact exactly -- 17 364 edges, all four kinds matching to
the unit, cross-file 10 045.

### Result

IntelliJ graph rebuilt from the scanner with no re-embedding (`scripts/build_graph_artifact.py`,
75 s scan + 13 s build): **1 157 273 edges, of which 1 081 652 cross-file**, up from 0.
Roughly 7.2 resolved in-repo import targets per file; the 64-cap rarely binds. Written to
`.code-diver/intellij-h37-jvm-graph.json` (786 MB) -- a NEW path, the June artifact that
existing reports depend on is untouched.

CodeSearchNet gets no rebuild. Its emptiness is intrinsic (1000 standalone functions, one per
file, no imports between them). Harmless: a zero graph term is identical across candidates,
so it is an additive constant that cannot reorder. The champion there is exactly the champion
with `graph_weight: 0`, which still exercises the seed mixture and the cross-encoder -- what
Finding 62 named as the binding constraint.

### Index staleness, resolved

After the `**/dir/**` exclusion fix, the IntelliJ audit came back: `only_in_scan` 206 864 ->
**0**, `only_in_index` 198 (files deleted from the repo since June), `content_differs` 544 of
149 614 shared, drift 0.50%. All 544 are `file_summary` items truncated past the new 200-char
head cap -- confirmed by locating the `...[truncated]` marker at the exact divergence offset.
Every `file_manifest` item is byte-identical. No reindex: it would buy 0.5% for hours of GPU.

### Standing caution

Two silent-inertness bugs in two days (`symbol_weight`, now `graph_weight` on 2 of 3 corpora),
both found only by reading the artifact rather than the config. A weight is not evidence that
a mechanism runs. Before any future arm on a new corpus, assert the mechanism is live -- for
the graph that means a non-empty file adjacency, asserted, not eyeballed.

## Finding 64 -- the champion does not transfer

Both approved arms ran, serially, alone on the machine, 1000 cases each, zero search failures.

* IntelliJ  `.code-diver/reports/intellij-h37-champion-xenc-1000.json`      1h38m
* CSN       `.code-diver/reports/codesearchnet-h37-champion-xenc-1000.json`   38m

### IntelliJ 1000 -- worse on both axes

| metric | June h3 | H37 champion | delta |
|---|---|---|---|
| file_recall@10 | 0.9025 | 0.8397 | -0.0627 |
| hit_rate@10 | 0.9280 | 0.8670 | -0.0610 |
| hit_rate@1 | 0.7340 | 0.6400 | -0.0940 |
| mrr@10 | 0.8147 | 0.7320 | -0.0827 |
| ndcg@10 | 0.8235 | 0.7457 | -0.0778 |
| file_precision@R | 0.7271 | 0.6296 | -0.0974 |
| search_duration_ms_mean | 3778 | 5895 | +56% |

Every metric down, latency up 1.56x. No trade to argue about -- it is dominated. Not noise:
`file_recall@10` CI95 [0.8179, 0.8616] excludes 0.9025 by a wide margin.

Unmatched pair, so this does NOT isolate a cause: June used `deterministic_postrank_h2` with
`locator_limit: 30`; H37 uses `graph_file_cross_encoder`. Strategy, locator width and graph
settings all differ at once.

What it DOES establish: the champion's absolute level transfers (protogen shown-recall 0.8354
vs IntelliJ 0.8397 -- the same number) but its *advantage* does not. It is not broken on a
monorepo, it is beaten there by a config tuned on that monorepo. Finding 60 landing on the
champion itself.

The pointed detail: the June config ran `expansion_depth: 0, neighbor_limit: 0` -- per Finding
63 its graph contributed nothing -- and it still won. Graph-off beat graph-on on IntelliJ,
inverting the protogen result. Prime suspect, not yet a conclusion: `graph_weight: 0.45` and
`depth: 2` were tuned when protogen's graph held ~10k cross-file edges over 1 911 files.
IntelliJ's rebuilt graph holds 1 081 652 over 74 906, hub files reaching 15 566 neighbours that
`neighbor_limit: 40` truncates arbitrarily. Depth-2 expansion from hubs plausibly floods the
pool with weakly-related files.

### CodeSearchNet Python 1000 -- a real but badly-priced gain

| arm | file_recall@10 | hit_rate@1 | ndcg@10 | ms/case |
|---|---|---|---|---|
| qwen3-0.6b baseline (same embedding as champion) | 0.9600 | 0.8220 | 0.8983 | 557 |
| **H37 champion** | **0.9700** | **0.8290** | **0.9081** | **2266** |
| embeddinggemma-300m baseline | 0.9750 | 0.8480 | 0.9180 | 787 |
| h9 body-evidence bounded (embeddinggemma) | 0.9860 | 0.8600 | 0.9304 | 1601 |

Against its own embedding model the champion is genuinely ahead: +0.010 recall, +0.007 hit@1,
+0.0098 ndcg. It costs +1709 ms/case -- 4x -- to buy that. And two embeddinggemma configs are
both better and faster, so the champion is off the CSN Pareto frontier entirely.

`graph_weight` is inert here by construction (no cross-file edges possible), so what CSN
measures is the seed mixture plus the cross-encoder. Read that way: the cross-encoder buys
about +0.01 recall for 4x latency on this corpus.

### Conclusion

The champion is protogen-specific. On both external corpora its retrieval-stack advantage
either vanishes (CSN: +0.01 for 4x latency, dominated by other configs) or reverses (IntelliJ:
-0.063 recall at 1.56x latency). The 0.8354 -> 0.8397 correspondence says the tuning did not
overfit to protogen's *difficulty*; it overfit to protogen's *shape*.

This does not retire the champion on protogen, where it remains the best measured config. It
retires the claim that the champion is a general setting, and it makes corpus-native tuning --
not further protogen tuning -- the thing worth spending GPU on.

### Next, in cost order (none started)

1. **Graph ablation on IntelliJ, one variable.** Same H37 config, `graph_weight: 0.0`. Isolates
   whether the JVM graph helps or hurts, which the unmatched June comparison cannot. ~1.6 h.
2. **Cross-encoder ablation on CSN.** Strategy `graph_file` without the rerank wrapper, same
   index. Prices the reranker exactly on a corpus where the graph is inert. ~15 min.
3. Only after 1-2: decide whether `neighbor_limit` needs to be degree-aware (hub truncation at
   40 out of 15 566 is arbitrary and untested).

## Finding 65 -- why the champion lost: five hypotheses, tested (2026-08-12)

Method: `/tmp/dsx/h38_probe.py` runs four variants over the SAME cases through the SAME
pipeline, sharing one loaded catalog and one warm profile cache so timings are steady-state.
Analysis (`/tmp/dsx/h38_analyze.py`) is paired -- an exact two-sided sign test over the
discordant pairs only. At n=150 the means have stderr ~0.03 and prove nothing; the paired
flips are the powerful read-out.

Variants: `champion` (as shipped), `graph0` (graph_weight 0), `depth0` (no propagation),
`lexseed0` (no full-corpus lexical scan). Corpora: IntelliJ 150 and CodeSearchNet 150, both
the first 150 cases -- NOT a random sample.

### Verdicts

| # | Hypothesis | Verdict |
|---|---|---|
| H38 | Graph propagation floods the top-10 with topologically-near, semantically-wrong files | **CONFIRMED** (IntelliJ) |
| H39 | The full-corpus lexical seed scan is the latency villain | **REFUTED** in magnitude, and it is load-bearing |
| H40 | The 34-candidate pool is too narrow | **REFUTED** on both corpora |
| H41 | The cross-encoder ranks badly at fixed width | **CONFIRMED but inverted** |
| H42 | On CSN the cost is the cross-encoder, not the scan | **CONFIRMED** (direction), prediction off in magnitude |

### IntelliJ 150 -- the graph is the problem

- `graph0` **+0.0671** recall@10 (14 better / 3 worse, p=0.01273). `depth0` identical to
  `graph0`, so the graph contributes nothing positive at any depth.
- Mechanism, measured: **31.3%** of champion top-10 slots hold a file that `graph0` does not
  rank anywhere in its 34-candidate pool -- it is there on graph score alone. Those slots carry
  **0.020** expected files per case, ~0.6% precision against ~10.7% overall: **~18x worse than
  the slots they displaced.** 41/150 cases hand the graph half the top-10 or more.
- Root cause is structural, in `graph_file_retrieval_strategy.py`: `_normalize` on the
  propagated scores guarantees the top graph-only file receives the full `graph_weight` (0.45),
  which exceeds the 0.25 a *perfect* pure-vector match can earn. The graph does not tie-break;
  it outranks.
- H39: the scan costs **732 ms, 22% of base** -- not the villain -- and removing it costs
  **-0.1889** recall (p=5.54e-06). Load-bearing.
- H40: ranking loses only **2.7%** of the pool ceiling.
- H41: the cross-encoder adds **+0.0748** (p=0.019) to the polluted champion pool but only
  **+0.0242** (p=0.2266, n.s.) once the graph is off. It is mostly repairing the graph's damage.
- Latency: cross-encoder **2247 ms of 5567 ms (40%)**. Graph propagation is free (-43 ms, noise)
  -- it costs only quality.
- Derived Pareto move: graph off + rerank off = **0.8380 at 3344 ms** vs champion 0.7951 at
  5567 ms. Better and 40% faster.

### CodeSearchNet 150 -- the graph is inert, the reranker is the whole bill

| variant | base_ms | rerank_ms | total_ms | pool@34 | top10 raw | top10 reranked |
|---|---|---|---|---|---|---|
| champion | 998 | 2015 | 3013 | 0.9655 | 0.9483 | 0.9655 |
| graph0 | 1104 | 2034 | 3138 | 0.9655 | 0.9483 | 0.9655 |
| depth0 | 1093 | 2010 | 3103 | 0.9655 | 0.9483 | 0.9655 |
| lexseed0 | 1097 | 1951 | 3048 | 0.9828 | 0.9397 | 0.9828 |

- `graph0` and `depth0` are **identical to the champion in all 116 analysed cases** -- 0
  graph-injected files, 0 flips. Cause found: the CSN graph artifact has 2000 items and
  **1000 edges, every one of kind `summarizes` connecting a file to itself**
  (`file_summary -> file_manifest`, same path). There is not a single cross-file edge, so
  propagation cannot move mass anywhere. `graph_weight` is dead code on this corpus.
- H42 CONFIRMED in direction: cross-encoder **2015 ms of 3013 ms (67%)**. The pre-registered
  prediction (`rerank_ms` ~1700, `base_ms` ~550) was directionally right and quantitatively
  off -- base is 998 ms, ~1.8x the predicted figure.
- The lexical scan is free here (-99 ms, i.e. noise) -- consistent with H39's finding that its
  cost scales with corpus size (149 614 items on IntelliJ vs ~2 000 here).
- H40 again refuted, harder: **0.0% of the pool ceiling is lost in ranking.** With one expected
  file per case and a 34-wide pool, if the file is in the pool it is in the top-10.
- The cross-encoder buys **+0.0172** (2 helped / 0 hurt / 114 tied, p=0.5, not significant) for
  67% of the latency. Dropping it is ~3x faster for no measurable recall loss.
- `lexseed0` *raises* pool recall here (0.9828 vs 0.9655), the opposite sign to IntelliJ, on 2
  discordant pairs (p=0.5). Suggestive only.

### Finding 66: the reranker has a 512-token ceiling and fails silently

Not a transient error -- a deterministic, reproducible defect found while running the above.

```
E srv send_error: task id = 473278, error: input (564 tokens) is too large to process.
                  increase the physical batch size (current batch size: 512)
```

At startup llama-server logs `embeddings enabled with n_batch (2048) > n_ubatch (512) ...
setting n_batch = n_ubatch = 512 to avoid assertion failure`. Non-causal pooling needs the whole
sequence in one physical batch, so **any query+document pair over 512 tokens fails the entire
/rerank request** -- all 34 documents, not just the long one. `max_document_chars: 850` (~250
tokens) plus a long CSN docstring query crosses it.

- Rate on CSN: **33/150 cases (22.0%)**, deterministic per query (all 4 variants, 3 retries each).
- Rate on IntelliJ: **zero** -- the earlier 150-case probe had no try/except at all, so its clean
  completion proves it. IntelliJ queries are short questions, not docstrings.
- `CrossEncoderRerankRetrievalStrategy.search()` swallows every rerank exception and returns
  base order. With `trace.enabled: false` this leaves **no evidence whatsoever** -- an unreranked
  run is indistinguishable from a reranked one.
- Impact on the completed 1000-case CSN arm (0.9700): ~22% of cases were never reranked, and
  reranking is worth +0.0172 where it works, so the arm understates its own configuration by
  roughly **0.004**. It stays off the Pareto frontier either way. The earlier check (21/25 top-10s
  differ from base order) proved reranking happened on most sampled cases; it did not prove it
  happened on all of them.

Tracked as task #36. Two fixes: relaunch :8081 with explicit `-b/-ub`, and make the swallowed
exception visible (warn regardless of trace, and carry a rerank-failure count into the report)
so no future arm can report base-order results as reranked.

### What this changes

Both corpora point the same way: the champion's two expensive additions are net-negative or
negligible off protogen. The graph either actively hurts (IntelliJ, -0.067) or is structurally
incapable of doing anything (CSN, no cross-file edges). The cross-encoder is the dominant
latency cost on both (40% / 67%) and, once the graph is off, buys nothing significant on either.

The next arms should therefore *subtract*, not add. Ranked by evidence strength:

1. **IntelliJ 1000, `graph_weight: 0.0`, one variable changed.** Confirms H38 outside the first
   150 cases. ~1.6 h exclusive GPU -- **needs a go-ahead before launching.**
2. **CSN, cross-encoder off.** ~15 min, prices the reranker exactly where the graph is inert.
3. Fix #36 before any further CSN measurement, or 22% of every future CSN arm is unreranked.
4. `neighbor_limit` degree-awareness is now lower priority: on IntelliJ the fix is to stop the
   graph outranking vector evidence, not to truncate hubs more cleverly.

### Caveats, stated plainly

- Both probes use the **first 150 cases, not a random sample.** The IntelliJ subset is harder
  than average (champion 0.795 here vs 0.8397 on the full 1000). Paired deltas are valid; the
  absolute levels are not comparable to the 1000-case numbers, and the implied ~0.907 for
  graph-off is a **prediction, not a measurement**.
- CSN figures exclude the 34 rerank-failed cases (22.7%). Those cases are not missing at random
  -- they are the long-query cases -- so the CSN numbers describe the short-query subset.
- CSN has one expected file per case, so recall@10 is a hit rate and moves in steps of 1/116.

---

## Finding 67 -- the four-arm campaign: the graph costs 5.6 recall points on IntelliJ

All four arms ran at n=1000, one at a time, with **zero rerank-failure warnings** (task #36's
fix held). Every pair is analysed paired on `case_id` with an exact two-sided sign test on the
discordant pairs only; ties carry no information and are excluded from the test.

| arm | recall@10 | nDCG | MRR | hit@10 | wall | s/case |
|---|---|---|---|---|---|---|
| IntelliJ champion (graph 0.45 + xenc) | 0.8397 | 0.7457 | 0.7320 | 0.8670 | ~98m ‡ | 5.88 ‡ |
| IntelliJ H38 (graph **off**, xenc on) | **0.8958** | 0.7725 | 0.7496 | **0.9250** | 182m28 † | 10.95 † |
| IntelliJ H43 (graph off, xenc **off**) | 0.8716 | **0.8110** | **0.8020** | 0.8990 | 33m21 | 2.00 |
| CSN champion postfix (graph + xenc) | **0.9730** | **0.9148** | **0.8952** | 0.9730 | 59m25 | 3.56 |
| CSN H44 (xenc **off**) | 0.9650 | 0.8857 | 0.8595 | 0.9650 | 9m08 | 0.55 |

† The 182-minute figure is **not a property of the configuration** -- see Finding 68. Graph-off
does strictly less work than the champion, so it cannot legitimately be 1.9x slower.

‡ The champion's wall time was reported by the earlier session's runner and is **not** in any
surviving log; only the report's mtime (2026-08-12 14:26:20) is verifiable. It is carried here
for orientation and carries the Finding 68 caveat too. The only wall times in this table backed
by a timestamped start *and* finish are H38, H43, and the two CSN arms.

### H38 confirmed at full scale: turning the graph off gains 5.6 points

Paired, IntelliJ 1000, H38 vs champion:

- `file_recall` +0.0561 (0.8397 -> 0.8958), **p = 7.3e-10**
- `ndcg` +0.0268, `file_reciprocal_rank` +0.0176, `file_hit` +0.0580

The pre-registered refutation condition was `recall@10 <= 0.8397`; the arm cleared it by 5.6
points. The 150-case probe predicted ~0.907 and the full corpus delivered 0.8958 -- the
prediction was slightly optimistic but the direction and rough magnitude both held.

`graph_weight: 0.45` was not a neutral default that failed to transfer. It was **actively
destroying** 5.6 points of recall on a JVM repository, because `GraphFileRetrievalStrategy`
injected neighbours with no resolvable import graph behind them (Finding 63) and those
injections outranked real vector evidence.

### H43: the cross-encoder buys recall and *costs* ranking quality

Paired, IntelliJ 1000, H43 vs H38 (single variable: `graph_file_cross_encoder` -> `graph_file`):

- `file_recall` **-0.0242** (0.8958 -> 0.8716), p = 0.0067
- `ndcg` **+0.0385** (0.7725 -> 0.8110), p < 1e-7
- `file_reciprocal_rank` **+0.0523** (0.7496 -> 0.8020), p < 1e-7

This is a genuine split, not a wash, and it is the most useful result of the campaign: **the
cross-encoder pulls relevant files into the top-10 while degrading the order at the very top.**
Both effects are significant and they point in opposite directions.

The mechanism is visible in the code. `_reranked` reorders candidates but never overwrites
`SearchResult.score`, and only `min(limit, len(rerank_candidates))` of the 34 candidates are
scored at all -- so the reranker promotes previously-unseen candidates into the window (recall
up) while shuffling the already-correct head (MRR down). `preserve_top_candidate` only defends
position 1, and only when the base margin clears `preserve_top_score_margin`.

My 150-case probe reported this as a null. It was a **power failure**, not a null: at n=1000
the recall effect is 0.0242 with p=0.0067. Recorded so the next probe is sized before it is
believed.

### H44: on CodeSearchNet the reranker is 85% of the runtime for no significant recall

Paired, CSN 1000, H44 vs champion-postfix:

- `file_recall` -0.0080, **p = 0.096 (not significant)**
- `ndcg` -0.0291, `file_reciprocal_rank` -0.0357, **p = 7.3e-07**
- wall 59m25 -> 9m08: the cross-encoder is **85% of the runtime**

The recall half of H44's pre-registered prediction is confirmed. The ranking half was **not
covered by the prediction** and did degrade significantly -- stated as an unpredicted result,
not as a hit.

CSN has one expected file per case, so recall@10 *is* hit@10 there (the two columns are
identical above, which is a useful internal consistency check).

### The 512-token fix, priced on its own

Champion CSN before the fix 0.9700 -> after 0.9730: **+0.0030** recall, 3 cases better and 0
worse, `ndcg` +0.0067 (p = 0.044). My pre-stated estimate was ~0.004. Small, real, and the
reason it matters is not the 0.003 -- it is that 22% of the arm was silently unreranked, so the
*old* number was not measuring what it claimed to measure.

### What this settles

The champion's graph is retired on non-Python repositories. Two candidate defaults remain, and
which one wins depends on what the consumer needs:

- **recall-first** (agent that reads all 10 files): graph off, cross-encoder **on**.
- **precision-first / latency-first** (top-1 or top-3 shown to a human): graph off, cross-encoder
  **off** -- 0.8110 nDCG at 2.00 s/case beats every other arm on both.

The default cannot be chosen from IntelliJ alone, because the cross-encoder's recall benefit is
IntelliJ-specific (CSN: p = 0.096). H45 tests both on protogen, the corpus the champion was
tuned on.

## Finding 68 -- 36 GB of swap, and why the H38 latency number is void

H38 took 182m28 where the probe predicted ~92m. I first blamed `ubatch 4096`. **That was wrong,
and the isolated measurement refuted my own hypothesis:** across 47 fixed payloads with pools
precomputed, 4096 costs only ~25% over 768 on IntelliJ (2203 ms vs 1645 ms), nowhere near 1.9x.

The real cause was machine state. At the end of the campaign:

```
vm.swapusage: total = 46080.00M  used = 44801.94M  free = 1278.06M
Pages occupied by compressor: 1795231   (= 27.4 GB of RAM holding compressed pages,
                                          storing 4585553 pages = ~70 GB uncompressed)
```

RSS for the long-lived model servers had collapsed to near zero -- the gemma-4-12B judge (up 5
days) and the mlx Qwen3.5-4B generator (up 7 days) were resident but **entirely paged out**.
Stopping both:

```
before   total = 46080.00M   used = 44801.94M
after    total = 10240.00M   used =  8806.25M
```

**36 GB of swap belonged to two servers that no search-axis arm uses.** Every latency number
measured while they were resident carries an unknown multiplicative factor, and the factor grows
with uptime -- which is exactly why the champion (14:26) looks fast and H38 (19:09-22:12) looks
slow. This is Finding 37 in its worst form, and it means:

- The quality columns above stand. The paired design is immune to a uniform time factor.
- The **wall/s-per-case column for H38 is void** and is being re-measured on a clean machine.
- Ordering effects within a sequential campaign are not benign. Arms must record machine state.

Two consequences, both now implemented:

1. `scripts/serve_judge.sh` and `scripts/serve_generator.sh` exist, so stopping a server before
   a timed arm no longer means losing the command that started it. Both carry the port guard and
   a comment saying why they should be down during retrieval measurement.
2. `/tmp/dsx/run_h45.sh` logs `vm.swapusage` after every arm. A latency claim without machine
   state next to it is not evidence.

### A methodological note on my own error

I told the user `ubatch 4096` had cost 4x before I had isolated it, reasoning from two arms that
differed in more than one variable. The isolated sweep refuted it. The lesson is the same one
Findings 57 and 60 already record, applied to latency instead of quality: **a mechanism inferred
from a difference between two multi-variable arms is a hypothesis, not a cause.**

### Addendum to Finding 68 -- latency and quality must not share an arm

The H38 re-run was launched to recover the void wall-clock figure. Partway through, the machine
was needed for interactive work, so the run was put on background QoS (`taskpolicy -b`, nice 20)
and Spotlight was stopped from indexing `.code-diver/` and the IntelliJ checkout. Measured
effect of the throttle: free pages 5469 -> 158627 (85 MB -> 2.5 GB).

That makes the re-run's wall-clock void for a second time, and the lesson is now clear enough to
be a standing rule:

**Latency and quality have different requirements and must be measured in separate runs.**
Quality needs n=1000 and tolerates any machine state, because the paired design cancels a time
factor. Latency needs an idle machine and no QoS interference, but only needs ~150 cases. Bundling
them means the scarcer requirement (an idle machine for hours) gates the cheaper one.

Also worth recording, because it removes an obvious-looking lever: `evaluation.workers` is
already `1`, so there is no eval concurrency to turn down. The eval's ~9.4 GB RSS is the file
catalog for 74 906 files, and it is intrinsic to the corpus, not a tunable. Throttling this
workload means QoS and priority, not parallelism.

---

## Finding 69 -- search-axis replay on IntelliJ is deterministic, which sharpens Finding 50a

The H38 re-run was paired against the original H38 report, same config, same dataset, 1000 cases:

| metric | original | re-run | delta | better | worse | tied |
|---|---|---|---|---|---|---|
| `file_recall` | 0.8958 | 0.8958 | +0.0000 | 0 | 0 | 1000 |
| `file_hit` | 0.9250 | 0.9250 | +0.0000 | 0 | 0 | 1000 |
| `ndcg` | 0.7725 | 0.7725 | +0.0000 | 1 | 0 | 999 |
| `file_reciprocal_rank` | 0.7496 | 0.7496 | +0.0000 | 0 | 0 | 1000 |

**999 of 1000 cases are byte-identical**; one case moved on nDCG alone. Finding 50a's "replay is
not bit-deterministic" was measured on the protogen *answer* axis, with a generator in the loop.
It does not describe the search axis: embedding lookup, hybrid merge, graph propagation and the
cross-encoder are all effectively deterministic here.

Two consequences:

1. Paired search-axis comparisons on IntelliJ carry **essentially zero replay noise**, so a sign
   test on them is measuring the intervention and nothing else. Every H38/H43/H46 delta in
   Finding 67 gets stronger, not weaker.
2. **Re-running a search-axis arm with an unchanged config buys nothing.** The only reason to do
   it is to change machine state -- which is exactly what the next section says failed.

## Correction to Finding 68 -- the swap explanation is NOT supported

I attributed H38's 182m28 to 36 GB of swap held by the judge and generator. The re-run, with both
servers stopped, came in at **231m01 -- slower, not faster.**

So the swap attribution fails. Stated plainly: **I was wrong twice about this latency figure**,
first blaming `ubatch 4096` (refuted by isolated measurement) and then blaming swap (refuted by
the re-run). The pattern in both cases was the same and is worth naming: I reasoned from a
difference between two runs that differed in more than one variable, and asserted a cause.

What is honestly known now:

- Neither 182m01 nor 231m01 is a clean measurement. The original ran under 44.8 GB of swap; the
  re-run ran at nice 20 under background QoS with interactive work in parallel. Both are void.
- The 36 GB of swap was real and stopping those servers was still correct -- it freed 2.5 GB of
  resident RAM. It just is not established as the cause of the slowdown.
- **The open question is now sharper, not answered:** is graph-off-plus-cross-encoder genuinely
  ~2x the champion's cost? That is surprising, because graph-off does strictly less work. If it
  is real, the mechanism is not yet identified -- `skip_when_top_margin_at_least` is None in both
  configs so neither skips reranking, `candidate_limit` is 34 in both, and `max_document_chars`
  caps every payload at 850 chars, so per-request rerank cost should be near-constant.

The instrument is phase 1 of `/tmp/dsx/run_followup.sh`: champion, H38, H43 and H46 over the same
150 seeded cases, each refusing to start until `load1 < 3.0`. Four arms under one guard is the
first setup in this campaign that can attribute a latency difference to a configuration at all.

Note on that runner: its header comment claims its arms run at nice 0. They run at **nice 5**,
inherited from the launching shell, and nice cannot be lowered without root. All four latency
arms share that nice, so their mutual comparison is sound; only the absolute s/case carries an
unknown offset. The comment was not corrected in place because the script was already executing.
