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
