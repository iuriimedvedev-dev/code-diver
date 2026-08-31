# 2026-08-30 — Champion promotion attempt: H-66b — NOT PROMOTED

Verdict: **NO PROMOTE**. The gate was fully evaluated this time — the full 1065
benchmark completed — and H-66b misses two of the four promotion floors.
`configs/intellij/intellij-h46-preserve-top.yml` remains the champion, untouched.

## 0. Keep-warm fix (the reason the run finished at all)

`scripts/keep_services_warm.py --quiet` was started before the benchmark and kept
alive for the entire session (both `:8001` vLLM embedder and `:8081` llama-server
reranker verified `200` before the run and again after it finished). Without it
macOS pages out the idle services under memory pressure and every query pays a
multi-second model reload.

Measured effect: the identical 1065 benchmark that consumed its entire 10800 s cap
on the earlier attempt (24 414 ms/query, no report produced) completed in
**1 h 37 m** here — start `18:10:37`, report written `19:48`, mean per-query
`5534 ms`. That is a **4.4x** reduction in per-query cost from the keep-warm alone,
with no config change. The pinger was still alive and both services still answering
`200` at the end of the run.

## 1. THE GATE — full 1065: COMPLETED

Config `configs/intellij/intellij-h66b-budget.yml`, collection
`intellij_h66b_budget_qwen`, dataset `datasets/intellij_eval_1000.answer_sets.jsonl`
(n=1065), `--limit 10`, `evaluation.workers: 1`. Report:
`/tmp/champion_h66b_1065.json` (3 190 731 bytes, 1065 results, 0 failed cases,
`degraded: false`). Run under a 21600 s `perl -e 'alarm ...'` cap; it finished well
inside it and was **not** killed.

### Overall

| metric | H-66b | H46 baseline | delta |
|---|---|---|---|
| recall@10 | **0.8175** | 0.8392 | −0.0217 |
| MRR@10 | **0.7117** | 0.7112 | +0.0005 |
| hit@1 | **0.6376** | 0.6263 | +0.0113 |
| ndcg@10 | **0.7235** | 0.7302 | −0.0067 |
| hit_rate@10 | 0.8338 | 0.8582 | −0.0244 |
| file_recall@10 | 0.8090 | 0.8311 | −0.0221 |
| map@10 | 0.6868 | 0.6897 | −0.0029 |

### Buckets (`file_recall@10`)

| bucket | n | H-66b | H46 | floor | result |
|---|---|---|---|---|---|
| path_symbol | 383 | **0.8138** | 0.8550 | 0.8350 | **FAIL −0.0212** |
| semantic | 603 | **0.8068** | 0.8221 | 0.8021 | PASS +0.0047 |
| workflow | 79 | **0.8027** | 0.7838 | 0.7638 | PASS +0.0389 |

### Decision rule

Promote only if recall@10 >= 0.8292 AND path_symbol >= 0.8350 AND
semantic >= 0.8021 AND workflow >= 0.7638.

- overall recall@10 `0.8175` < `0.8292` → **missed by 0.0117**
- path_symbol `0.8138` < `0.8350` → **missed by 0.0212**
- semantic `0.8068` ≥ `0.8021` → pass
- workflow `0.8027` ≥ `0.7638` → pass

Two of four floors missed ⇒ **NO PROMOTE**.

Shape of the loss: H-66b is not uniformly worse. It *beats* H46 on hit@1
(+0.0113), ties on MRR@10, and clearly wins the workflow bucket (+0.0189 over H46,
the best workflow number on record). It loses on depth — hit@3/@5/@10 all drop and
recall@10 falls 0.0217 — and the damage is concentrated in `path_symbol`, exactly
the bucket the compact-budget summary was expected to help. The compact budget
trades tail recall for top-1 precision; the gate is a recall gate, so it fails.

## 2. Latency

| stat | H-66b (this run) | archived H46 |
|---|---|---|
| mean | **5534 ms** | 3994 ms |
| p95 | **9947 ms** | 5974 ms |
| total | 5 893 989 ms | 4 253 232 ms |

Median is **not available**: the report stores only aggregate
`search_duration_ms_*` keys, per-case durations are not persisted in `results`.

**Caveat — this is not a valid latency comparison.** The archived H46 3994 ms was
measured on a different day on a differently-loaded machine and without the
keep-warm pinger. The only sound latency statement here is the intra-session one:
keep-warm cut H-66b from 24 414 ms/query to 5534 ms/query. Any H-66b-vs-H46 latency
claim needs a fresh H46 run under the same warm conditions, which was not done.

## 3. Fixed kind diagnostics (`winning_index_kind`)

The diagnostics now read the new `winning_index_kind` metadata key and report the
point that actually won, instead of always reporting `file_summary`.

| diagnostic | H-66b (1065) | H46 (1065, old code) |
|---|---|---|
| `top_result_kind.file_summary` | 0.6582 | 0.9944 |
| `top_result_kind.file_manifest` | **0.3418** | 0.0056 |
| `first_relevant_kind.file_summary` | 0.5923 | 0.9978 |
| `first_relevant_kind.file_manifest` | **0.4077** | 0.0022 |
| `first_relevant_kind.none` | 0.1662 | 0.1418 |

The manifest lane wins the top slot on **34%** of queries and supplies the first
relevant hit on **41%** — it is doing real work, not decoration. This confirms the
old "the kind never surfaces" kill verdicts (H-66c, base H-64) were measurement
artefacts. (`none` 0.1662 is just the complement of hit_rate@10 0.8338.)

For reference, WHERE-79 on the same config earlier today: `top_result_kind`
file_summary 0.8861 / file_manifest 0.1139; `first_relevant_kind` file_summary
0.9423 / file_manifest 0.0577, `none` 0.3418; recall@10 0.5842, MRR@10 0.3543,
hit@1 0.2278, ndcg@10 0.3869 (report `/tmp/champion_h66b_where79.json`).

## 4. Configs

`configs/intellij/intellij-champion.yml` was **not** created — the gate failed.
`configs/intellij/intellij-h46-preserve-top.yml` remains the champion and was not
edited. `configs/intellij/intellij-h66b-budget.yml` unchanged. No reindex, no git
commits, no processes killed that this session did not start.

## Open items

1. The path_symbol regression (−0.0412 vs H46) is the single blocker. The compact
   budget drops keyword/path noise from the terms section and shortens the
   embedded `file:` line to basename + last two segments — precisely the signal
   `path_symbol` queries key on. Try an arm that keeps the full path line while
   retaining purpose-first ordering.
2. H-66b's workflow win (0.8027 vs 0.7838) and hit@1 win (0.6376 vs 0.6263) are
   worth keeping. A blend — H46 path representation plus H-66b purpose-first
   summary head — is the obvious next hypothesis.
3. Latency: re-measure H46 warm before making any latency claim. The 5534 ms vs
   3994 ms gap is currently unattributable between config and machine state.
4. Keep-warm should be treated as standard procedure for every future benchmark;
   it is the difference between a 1.6 h run and a run that cannot finish in 3 h.

---

# 2026-08-30 (later) — H-66d "full path" arm — NOT PROMOTED (stopped at the WHERE-79 screen)

Follow-up to open item 1 above: keep H-66b's purpose-first ordering and term
noise filter, but restore the full embedded `file:` line that `path_symbol`
queries key on. Champion `configs/intellij/intellij-h46-preserve-top.yml`
remains untouched; no promotion.

## 1. Code change — the monolithic flag is now split

`file_summary_compact_budget` did three things at once. Path shortening is now
independently controllable via a new **`file_summary_compact_path`** option
(tri-state `bool | None`, default `None` = follow `compact_budget`, so every
existing config, including `intellij-h66b-budget.yml`, is bit-identical).

Plumbed through: `settings/defaults.py` (`FILE_SUMMARY_COMPACT_PATH = None`),
`config/scanner_config.py`, `config/config_loader.py`, `services/codebase_scanner.py`,
`orchestration/orchestrated_codebase_scanner.py`, `cli.py`, and
`services/file_summary_item_builder.py`.

Bug found by the new tests: `build()`'s non-compact branch hard-coded
`f"file: {rel_path}"` instead of calling `_file_line_value`, so `compact_path=True`
alone had no effect. Both branches now share the helper. Output for
`compact_path in (None, False)` is unchanged.

Tests: 3 added to `tests/unit/test_file_summary_item_builder.py` (full path kept
when the new option is off while purpose-first + term filtering still apply;
compact path when on without `compact_budget`; `None` follows `compact_budget`).
`uv run pytest tests/unit -q` → **1230 passed, 3 skipped**. No test weakened.

New config `configs/intellij/intellij-h66d-fullpath.yml`: copy of h66b,
`file_summary_compact_budget: true`, `file_summary_compact_path: false`,
collection `intellij_h66d_fullpath_qwen`, suite `h66d-fullpath`.

## 2. Reindex

| item | value |
|---|---|
| collection | `intellij_h66d_fullpath_qwen` |
| points (Qdrant) | **136578** |
| composition | file_summary=68289, file_manifest=68289, unique_paths=68289 |
| content | 286.41 MB, mean 2097 B |
| wall time | **1868 s = 31 m 08 s** |
| exit | 0 |

## 3. WHERE-79 screen — FAILED

`datasets/intellij_eval_where_only.jsonl` (n=79), `--limit 10`, workers 1,
keep-warm alive, both services `200` before and after. Report
`/tmp/h66d_where79.json`. Wall time 399 s.

| metric | H-66d | H-66b | H46 | vs H-66b | vs H46 |
|---|---|---|---|---|---|
| recall@10 | **0.5652** | 0.5842 | 0.5916 | −0.0190 | −0.0264 |
| MRR@10 | **0.3486** | 0.3543 | 0.3472 | −0.0057 | +0.0014 |
| hit@1 | 0.2278 | 0.2278 | — | 0.0000 | — |
| ndcg@10 | 0.3813 | 0.3869 | — | −0.0056 | — |
| hit_rate@10 | 0.6329 | — | — | | |
| map@10 | 0.3078 | — | — | | |

Buckets, `file_recall@10`: path_symbol (9) 0.6667, semantic (53) 0.5374,
workflow (17) 0.5980.

**Screen rule: run the full 1065 only if WHERE-79 recall@10 >= 0.57.**
`0.5652 < 0.57` → **missed by 0.0048**. The full 1065 gate was therefore
**not run**; `/tmp/h66d_1065.json` does not exist and no 1065 numbers are
reported. Restoring the full path did not recover the path signal on this
screen — it came in *below* both H-66b and H46.

## 4. Kind diagnostics (`winning_index_kind`-backed) — WHERE-79

| diagnostic | H-66d | H-66b (WHERE-79) |
|---|---|---|
| `top_result_kind.file_summary` | 0.8861 | 0.8861 |
| `top_result_kind.file_manifest` | 0.1139 | 0.1139 |
| `first_relevant_kind.file_summary` | 0.9200 | 0.9423 |
| `first_relevant_kind.file_manifest` | 0.0800 | 0.0577 |
| `first_relevant_kind.none` | 0.3671 | 0.3418 |

## 5. Latency (WHERE-79, warm)

| stat | H-66d | H-66b (WHERE-79 run) |
|---|---|---|
| mean | **4967 ms** | not recorded per-run above |
| p95 | **4721 ms** | — |
| total | 392 390 ms | — |

Median unavailable: the report persists only aggregate `search_duration_ms_*`.

## 6. Verdict

**NO PROMOTE.** H-66d failed the WHERE-79 screen (0.5652 < 0.57) and the four
full-1065 promotion floors (0.8292 / 0.8350 / 0.8021 / 0.7638) were never
evaluated for this arm. `intellij-champion.yml` was not created.
`intellij-h46-preserve-top.yml` is unchanged and remains the champion.

## 7. What this rules out

The path_symbol regression of H-66b is **not** caused by the shortened `file:`
line alone. Restoring the full path while keeping purpose-first ordering and the
term filter made WHERE-79 slightly *worse*, so the loss must come from (a) the
purpose+terms reordering pushing path tokens past the 500-char embedder
truncation, or (b) the keyword/path stopword filter stripping `src`/`com`/
`intellij`/`impl` tokens that path queries match on. The next arm should split
those two remaining behaviours and test (b) first — the stopword list removes
exactly the path segments `path_symbol` queries contain.
