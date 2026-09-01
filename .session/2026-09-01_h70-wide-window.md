# H-70 — wide embedding window (500 chars -> 1800 chars)

**Verdict: DO NOT PROMOTE.** Measured loss on WHERE-79 against a same-sitting champion floor.

## Hypothesis

The indexed `file_summary` was capped at 500 CHARACTERS while the embedder
(`mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`, `max-model-len 512`) has a 512-TOKEN window.
Claim: we waste ~4x of the window; feeding more of the summary should improve retrieval.

The premise was verified and is TRUE. The conclusion is FALSE — more context made retrieval worse.

## What actually enforced the cap

`embedding.max_input_chars` (`configs/intellij/intellij-h66b-champion.yml: 500`). It was already a
config option, not a hidden constant. The genuinely hard-coded values were the token window itself:
`_MODEL_MAX_TOKENS = 512` / `_TOKEN_SAFETY_MARGIN = 32`, duplicated in
`openai_embedding_provider.py` and `embedding_text_preparer.py`. Those are now configurable
(`embedding.max_input_tokens`, `embedding.token_safety_margin`), defaults unchanged.

## Token-length distribution (200 IntelliJ files, seed 70, embedder's own Qwen tokenizer)

`scripts/measure_summary_token_lengths.py`. Includes the `document_prefix`.

| budget | median tok | mean | p90 | p95 | p99 | max | >512 tok | char-capped |
|---|---|---|---|---|---|---|---|---|
| uncapped | 553 | 1044 | 1734 | 1178* | — | 8875 | 52.0% | — |
| **500 chars (champion)** | **109** | 108 | 128 | 131 | 140 | 163 | **0%** | **96.5%** |
| **1800 chars (H-70)** | **370** | 355 | 421 | 432 | 460 | 491 | **0%** | 63.5% |
| 1900 chars | 390 | 374 | 444 | 455 | 484 | 496 | 0% | 61.0% |

The champion used ~21% of the window; 1800 chars uses ~72% with zero model-window overflow and
1/200 over the 480-token effective budget (512 - 32 margin). 1800 was chosen over 1900/1965 for
headroom. **The premise was correct — the window really was being wasted.**

## Same-sitting WHERE-79 (79 cases, `datasets/intellij_eval_where_only.jsonl`, limit 10)

Both arms run back-to-back on 2026-09-01, both with `seed_score_parity: true`.

| metric | champion h66b (500ch) | H-70 (1800ch) | delta |
|---|---|---|---|
| recall@10 | **0.6120** | 0.5508 | **-0.0612** |
| MRR@10 | **0.3679** | 0.3446 | -0.0233 |
| hit@1 | 0.2278 | **0.2405** | +0.0127 |
| hit@10 | **0.6835** | 0.6203 | -0.0633 |
| nDCG@10 | **0.4095** | 0.3752 | -0.0343 |
| latency mean | **5600 ms** | 6232 ms | +632 ms |
| latency p95 | **7329 ms** | 9102 ms | +1773 ms |

The champion reproduced its archived seed-parity number 0.6120/0.3679 exactly, so the floor is
trustworthy and the box was not drifting during this sitting.

Guard slice and the 1065 gate were **not run** — the step-6 precondition ("only if WHERE improves")
was not met.

## Why it likely fails

The compact summary is deliberately ordered best-signal-first (purpose+terms, then symbols, then
head). The 500-char cap was not just a limit, it was an implicit *precision filter*: only the
highest-signal lines reached the vector. Feeding 3.4x more tokens dilutes the embedding with
imports, boilerplate and file-head noise, pulling vectors toward a generic "Java file" centroid.
hit@1 rising while recall@10 falls is consistent with this — a few queries get sharper, but the
pool of plausible files collapses.

Cost side: indexing went from ~35 min to **~1h40m** (136,152 points), and search p95 rose 24%.

## Recommendation

**No promote.** Keep `max_input_chars: 500`. The window is genuinely underused, but naively filling
it is harmful. If revisited, the lever is *what* fills the window (more symbols / call sites /
docstrings, ranked by signal), not simply a larger char budget. A cheaper intermediate probe
(e.g. 900 chars) could locate the turning point, but the -0.06 recall at 1800 suggests the gradient
points the wrong way.
