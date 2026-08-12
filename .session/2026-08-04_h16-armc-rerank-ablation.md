# 2026-08-04 — H16 arm C (LLM rerank ablation) result

Run: `ARM=c CONTEXT_FILES=4 CONTEXT_LINES=160 ./scripts/run_h16_arm.sh`
Report: `.code-diver/reports/protogen-h16-armc-qwen35-4b-100.json`
Baseline: `.code-diver/reports/strict-judge/h14-qwen35-4b-answer-strict-qwen35-9b.json`
100/100 cases, 0 errors, matched pairs. Only variable changed: `--agentic-query-rerank` removed.

## Verdict: hypothesis REFUTED. Keep the reranker.

| metric | rerank on | rerank off | Δ | up/down | p or CI |
|---|---|---|---|---|---|
| `citation_expected_recall` (primary) | 0.610 | 0.465 | **−0.145** | — | [−0.208, −0.082] |
| `candidate_file_recall` | 0.715 | 0.600 | −0.115 | — | [−0.167, −0.063] |
| `candidate_bundle_complete` | 0.620 | 0.480 | −0.140 | 1/15 | **0.0005** |
| `context_bundle_complete` | 0.460 | 0.310 | −0.150 | 0/15 | **0.0001** |
| `answer_grounded` | 0.720 | 0.580 | −0.140 | 4/18 | **0.0043** |
| `citation_fabricated_rate` (guardrail) | 0.054 | 0.095 | +0.041 | — | [−0.007, 0.088] |
| s/case | 104.0 | 87.7 | −16% | | |

Every quality metric degrades, the guardrail worsens, and the only gain is the
16% latency cut. The LLM reranker earns its 13.5 s/case.

## Finding 12 — the observational signal was confounded, as flagged

Pre-run evidence (from saved reports) said the reranker was dead weight: in the
40 cases where it returned a **single** candidate of 34 — leaving 9 of 10 slots
to deterministic backfill — outcomes were *better* than the 53 fully-reranked
cases (bundle 0.450 vs 0.434, grounded 0.750 vs 0.698).

That comparison was confounded by case difficulty and was labelled as such
before the run. The resolution: the reranker returns one candidate precisely on
easy cases where the deterministic top-1 is already right. The observational
split therefore credited *backfill* with the reranker's easy wins, while the
hard cases — where reranking actually reorders usefully — sat in the other
group and dragged its average down.

Lesson: a within-run split by a model's own behaviour is not an ablation. The
model's choice of how many candidates to return is itself an outcome, so
grouping on it conditions on a collider. Only the ablation could settle it, and
it cost 2.5 GPU hours to overturn a conclusion that looked free.

## Finding 13 — the metric framework validated itself

`answer_grounded` moved here (−0.140, p = 0.004) but did **not** move in H15
(+0.020, p = 0.77). That is exactly what Finding 9 predicts, not a contradiction:

- H15 changed only whether the *second* expected file reached context.
  `answer_grounded` needs just one on-target citation, so it is blind to that.
- Arm C degraded whether *any* expected file was retrieved at all
  (`candidate_file_recall` −0.115). `answer_grounded` can see that.

So the metric behaves correctly and its blind spot is precisely characterised.
`citation_expected_recall` detected both interventions (+0.055 in H15, −0.145
here) and remains the right primary.

## Consequences

- **Rerank stays on** for every subsequent arm, including arm B.
- Retrieval quality is more fragile than assumed: removing one LLM call costs
  0.115 of `candidate_file_recall`. The deterministic ranking alone is
  substantially worse than the pipeline's headline numbers suggest.
- This raises the prior on arm B (depth). If reranking 34→10 is worth this
  much, the ordering within the candidate pool matters a great deal, and a
  larger pool with the reranker still active is a reasonable bet.
- Arm D (`--query-count 8`) also gains value: more probe queries widen the pool
  the reranker draws from, at no extra LLM call.

## Open

- Arm C rejudge was still running when this was written; judge scores are
  secondary and not needed — every deterministic metric agrees on the verdict.
- Output naming flaw: `protogen-h16-armc-qwen35-4b-100.json` does not encode
  the context budget, so re-running arm C at another budget would silently
  overwrite this file. Fix before extending the series.
