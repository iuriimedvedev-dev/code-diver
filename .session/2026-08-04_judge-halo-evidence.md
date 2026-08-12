# 2026-08-04 — E2/E3: judge halo effect, measured

Track: audit items E2 (fix the judge) + E3 (promote `context_bundle_complete`).
Data: `.code-diver/reports/strict-judge/h14-*-answer-strict-qwen35-9b.json`
(4 H14 answer runs, strict prompt, judged by qwen35-9b, n = 96–99 each).

## Finding 1 — the six criteria are one criterion

Mean pairwise Spearman between the six judge criteria:

| run | mean inter-criterion ρ | min | max | ρ(halluc, correctness) |
|---|---|---|---|---|
| gemma4-e2b  | 0.792 | 0.59 | 0.97 | 0.846 |
| gemma4-e4b  | 0.703 | 0.44 | 0.91 | 0.765 |
| qwen35-4b   | 0.657 | 0.27 | 0.95 | 0.849 |
| qwen35-9b   | 0.715 | 0.38 | 0.96 | 0.880 |

`hallucination_control` and `answer_correctness` measure different things — an
answer can be correct but partly fabricated, or wrong without fabricating
anything. ρ ≈ 0.85 says the judge is not distinguishing them. `judge_overall`
is a weighted average of six terms whose effective dimensionality is ~1, so
it is a single "does this look good" score wearing six hats.

Consequence: the 4.21 vs 4.28 gap between qwen35-4b and qwen35-9b is one noisy
axis, not a six-criteria consensus. Do not rank configurations on it.

Human half of the halo probe still pending — needs the hand-labelled anchor set
(`scripts/build_judge_anchor_set.py` → `scripts/validate_judge.py`). The machine
half above is already conclusive on its own terms.

## Finding 2 — `judge_specificity` is a dead criterion

Per-criterion stdev (0–4 scale):

| run | correctness | grounding | coverage | citation | **specificity** | halluc |
|---|---|---|---|---|---|---|
| gemma4-e2b | 1.60 | 1.61 | 1.40 | 1.64 | **1.03** | 1.78 |
| gemma4-e4b | 1.44 | 1.45 | 1.30 | 1.35 | **0.53** | 1.71 |
| qwen35-4b  | 1.18 | 1.28 | 1.13 | 1.07 | **0.25** | 1.52 |
| qwen35-9b  | 1.07 | 1.15 | 0.98 | 1.12 | **0.50** | 1.66 |

On three of four runs `specificity` is near-constant. It discriminates nothing
while consuming 10% of the `judge_overall` weight — pure dilution.

## Finding 3 — hallucination is *not* free (audit partly overstated)

Cases scoring 0 on `hallucination_control` average `judge_overall` 1.02 / 1.56 /
1.82 / 2.26 across the four runs — the other criteria drop with it. Only 0–2
cases per run combine `hallucination_control == 0` with `judge_overall > 3.5`.

So the audit's "fabricates and still scores well" is a tail case, not the
central tendency. The systemic problem is Finding 1, not lenient weighting.
This *is* consistent with Finding 1: halluc=0 drags everything down because the
criteria co-move.

## Finding 4 (infra defect) — rejudge drops the deterministic metrics

`scripts/rejudge_answer_report.py` writes `"metrics"` containing only
mean-aggregated `judge_*` keys. It discards `answer_grounded`,
`context_bundle_complete`, `candidate_file_hit`, `citation_fabricated_rate`,
and every `_ci95_*` suffix that `AnswerMetrics.aggregate()` /
`EvaluationStatistics` would have produced.

Effects:
- The strict-judge reports cannot be used for E3 primary-metric reporting;
  you must cross-reference the un-judged report in `.code-diver/reports/`.
- There are **no confidence intervals on `judge_overall` anywhere**, which is
  why the H14 sweep table was compared without error bars.

Fix: rejudge should re-run `AnswerMetrics().aggregate(rows)` over the merged
rows (as `AnswerReportJudge.judge_payload` already does) instead of hand-rolling
a judge-only mean. Queued as a follow-up unit.

## Finding 5 — the judge is mostly restating `context_bundle_complete`

Spearman between `context_bundle_complete` and `judge_overall`, per run:

| run | n | ρ | judge \| bundle=1 | judge \| bundle=0 | gap |
|---|---|---|---|---|---|
| gemma4-e2b | 96 | 0.423 | 4.43 | 3.32 | 1.11 |
| gemma4-e4b | 99 | 0.535 | 4.66 | 3.46 | 1.20 |
| **qwen35-4b** | 97 | **0.762** | **4.99** | 3.79 | 1.20 |
| qwen35-9b | 99 | 0.443 | 4.71 | 3.99 | 0.72 |

For the promoted model the judge score is largely a proxy for whether retrieval
delivered a complete bundle, and it **saturates at 4.99/5 whenever it did** —
no discrimination among successful cases. Together with Finding 1 (six criteria
≈ one axis) this means `judge_overall` carries little information beyond a
metric we already compute deterministically and for free.

Practical rule: rank configurations on `context_bundle_complete` and
`answer_grounded`. Use the judge only for the residual — cases where the bundle
was complete and the answer still failed.

## Finding 6 — the qwen35-4b promotion is a latency win, not a quality win

With confidence intervals now available (they did not exist before this
session — see Finding 4):

| | qwen35-4b | qwen35-9b |
|---|---|---|
| `context_bundle_complete` | 0.460 [0.366, 0.557] | 0.460 [0.366, 0.557] |
| `answer_grounded` | 0.720 [0.625, 0.799] | 0.700 [0.604, 0.781] |
| `judge_overall` | 4.21 | 4.28 |
| mean latency | **104 s** | 125 s |

Identical bundle completeness, near-total CI overlap on grounding. The
promotion stands, but on the grounds of "indistinguishable quality, 17%
faster" — not "better grounded".

## Finding 7 — the E1 confound, quantified

`context_bundle_complete` is a retrieval metric, yet it splits by model family:
qwen 0.46 / 0.46 vs gemma 0.37 / 0.35, with `answer_grounded` tracking it
(0.72 / 0.70 vs 0.50 / 0.53). Because one model does planning, reranking AND
answering in H14, model choice moves the primary metric **through retrieval,
not generation**.

This reframes the local-model question: the dominant effect is which small
model plans queries and reranks, not which one writes the answer. Raises the
value of E1's role decoupling above what the audit assumed.

## Finding 8 — judge infrastructure failures are scored as zero-quality answers

`AnswerMetrics.aggregate()` (and the old hand-rolled rejudge aggregation) both
read per-case values as `.get(key, 0.0)`. A row whose judging FAILED — a
`judge_error`, e.g. `SchemaViolationError` after the repair attempts are
exhausted — carries no `judge_*` keys, so it is averaged in as 0.0. An
infrastructure failure is recorded as a quality measurement.

Measured on `.code-diver/reports/strict-judge/`:

| run | excluded | reason | JO (judged rows) | JO (as reported) | penalty |
|---|---|---|---|---|---|
| gemma4-e2b | 4 | 1 gen error, 3 judge errors | 3.738 | 3.589 | −0.150 |
| gemma4-e4b | 1 | 1 judge error | 3.879 | 3.841 | −0.039 |
| qwen35-4b | 3 | 3 judge errors | **4.336** | 4.206 | −0.130 |
| qwen35-9b | 1 | 1 judge error | **4.320** | 4.277 | −0.043 |

**This reverses a ranking.** On rows the judge actually scored, qwen35-4b leads
qwen35-9b (4.336 vs 4.320). As reported, 9b leads (4.206 vs 4.277). The whole
gap is the artifact of unequal judge-error counts — the sweep ranked the models
by how often the judge crashed, not by answer quality.

Distinguish three cases, not two:
1. Unjudgeable row (empty prediction / generation error) → explicit zeros,
   included. An empty answer really is worth zero.
2. Judging failed (`judge_error`) → EXCLUDED from judge means. A missing
   measurement, not a bad one. Keep `judge_error_count` for visibility.
3. Judged normally → unchanged.

Also add a `judge_scored_count` aggregate so judge coverage is visible on the
face of the report; that alone would have made this artifact obvious.

Correction to an earlier reading: the rejudge path did NOT *exclude* unjudged
rows and inflate the means. `.get(key, 0.0)` counted them as zeros. The bias
runs the other way.

## Also note

Judged H14 reports live in `.code-diver/reports/strict-judge/`, not the
top-level `reports/` dir. The un-judged `protogen-h14-*-text-graph-100.json`
files carry no judge scores at all (only `judge_duration_ms`).

## Corrected H14 table (re-aggregated through the fixed code path)

| run | judge_overall | 95% CI | scored | bundle_complete | grounded |
|---|---|---|---|---|---|
| gemma4-e2b | 3.738 | [3.373, 4.104] | 96 | 0.370 | 0.530 |
| gemma4-e4b | 3.879 | [3.573, 4.186] | 99 | 0.350 | 0.500 |
| qwen35-4b | **4.336** | [4.073, 4.598] | 97 | 0.460 | 0.720 |
| qwen35-9b | 4.320 | [4.074, 4.567] | 99 | 0.460 | 0.700 |

qwen35-4b is nominally ahead of 9b now rather than behind, but the intervals
overlap almost entirely. Conclusion: indistinguishable on quality, 4b wins on
latency (104 s vs 125 s). The promotion stands, on corrected grounds.

## Next

- **Blocked on a human:** label the 30 cases in
  `.code-diver/anchors/h14-qwen35-4b-anchor30.md`, then run
  `scripts/validate_judge.py` for the human half of the halo probe.
- **E1 is now the highest-value experiment**, upgraded by Finding 7: the model
  choice moves the primary metric through retrieval, not generation, so
  decoupling planner / reranker / answerer roles is worth more than the audit
  assumed. Re-run the 2x2 grid on the fixed measurement stack.
- Consider dropping or replacing `judge_specificity` (Finding 2), and
  down-weighting `judge_overall` in favour of `context_bundle_complete`
  (Finding 5).
- Existing reports in `.code-diver/reports/strict-judge/` were produced by the
  old aggregation. Re-run `scripts/rejudge_answer_report.py` over them to
  regenerate with deterministic metrics, CIs and `judge_scored_count`, or treat
  the re-aggregated numbers above as authoritative.

## Shipped this session

- Abstention is now a first-class judge output (`answer_type` enum in
  `JUDGE_SCHEMA`, enforced deterministically in `AnswerJudgeRubric`, new
  `judge_abstained` / `judge_empty_answer` binary metrics).
- Malformed judge payloads raise `AnswerJudgePayloadError` instead of becoming
  silent all-zero scores that were polluting every aggregate mean.
- Previously discarded generation `confidence` captured as `answer_confidence`.
- Anchor harness: `scripts/build_judge_anchor_set.py`,
  `scripts/validate_judge.py` (stratified sampling + agreement + halo probe).
- `context_bundle_complete` promoted to the primary metric across `cli.py`,
  `answer_report_metrics.py` and `summarize_h14_run.py`; the six criteria are
  reported individually; the sum-of-criteria composite is deleted everywhere.
- `compare_judges.py` now does per-criterion agreement instead of sum
  correlation, plus abstention agreement.
- `rejudge_answer_report.py` aggregates the full merged row set, so re-judged
  reports keep the deterministic metrics and all `_ci95_*` suffixes.
- Rate confidence intervals clamped to [0, 1] (`evaluation_statistics.py`);
  unbounded and 0-4 / 0-5 scale metrics deliberately left unclamped.
- `unjudgeable_row_policy.py`: one shared policy for empty/errored rows, wired
  into all three judge call sites (rejudge script, `AnswerReportJudge`,
  `AnswerEvaluator`), replacing three divergent implementations.
- `judge_*` score keys now average present-only, so a `judge_error` is excluded
  rather than counted as 0.0; new `judge_scored_count` exposes judge coverage.
- `answer_type` made optional in `JUDGE_SCHEMA` (judge yield over schema rigor),
  with a new `judge_answer_type_missing` metric so the resulting coercion to
  `"substantive"` stays observable instead of silent.

Unit tests: 742 at session start → **799**.
