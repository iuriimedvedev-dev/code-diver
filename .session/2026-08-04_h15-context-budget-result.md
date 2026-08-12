# 2026-08-04 — H15 (context budget 4→10 files) result

Run: `CONTEXT_FILES=10 CONTEXT_LINES=160 ./scripts/run_h14_model.sh qwen35-4b qwen35-9b`
Report: `.code-diver/reports/protogen-h14-qwen35-4b-text-graph-100-cf10-cl160.json`
Baseline: `.code-diver/reports/strict-judge/h14-qwen35-4b-answer-strict-qwen35-9b.json`
100/100 cases, 0 errors, matched pairs on `case_id`.

## Headline: mechanism confirmed, pre-committed criterion null

| metric | cf4 | cf10 | Δ | up/down | p |
|---|---|---|---|---|---|
| `context_bundle_complete` | 0.460 | 0.600 | +0.140 | 14/0 | **0.0001** |
| `candidate_bundle_complete` | 0.620 | 0.600 | −0.020 | 1/3 | 0.63 |
| `answer_grounded` | 0.720 | 0.740 | +0.020 | 7/5 | 0.77 |
| `citation_fabricated_rate` | 0.054 | 0.042 | −0.012 | — | CI spans 0 |
| s/case | 104.0 | 112.9 | +8.5% | | |

`context_bundle_complete` reached 0.600 against a candidate ceiling of 0.600 —
the truncation loss is **fully** eliminated, exactly as the free simulation
predicted (it forecast 0.620 at budget 10). The mechanism works.

`answer_grounded` did not move. The −0.020 on `candidate_bundle_complete`
is query-planner nondeterminism; it sets the noise floor at ~±0.02–0.05.

## Finding 9 — `answer_grounded` is structurally blind to this intervention

`AnswerGroundingMetrics.score` (`answer_grounding_metrics.py:52`):

```python
grounded = bool(answer.strip()) and bool(cited) and not fabricated and bool(on_target)
```

`on_target` is non-empty as soon as **one** cited path is an expected path.
For the 62 cases with ≥2 expected paths, a case scores `answer_grounded = 1.0`
with only the first expected file cited. H15 intervenes precisely on the
*second* file. The pre-committed criterion cannot see the treatment.

Confirmed empirically: the 14 cases whose bundle flipped 0→1 were **already**
at `answer_grounded` 0.929 before the flip and 0.929 after — one up, one down.

## Finding 10 — the bundle→grounding correlation is a selection effect

Cross-sectionally the association looks overwhelming:

| | n | `answer_grounded` | `citation_fabricated_rate` |
|---|---|---|---|
| cf4, bundle complete | 46 | 0.978 | 0.000 |
| cf4, bundle incomplete | 54 | 0.500 | 0.100 |
| cf10, bundle complete | 60 | 0.950 | 0.017 |
| cf10, bundle incomplete | 40 | 0.425 | 0.080 |

But under intervention the effect is zero (above). Cases that *naturally* get
complete bundles are the easy ones, which are also the ones the model grounds
well. Completing a bundle by force does not transfer the easy-case grounding
rate to a hard case.

This directly qualifies Finding 5's practical rule ("rank configurations on
`context_bundle_complete`"). That metric is a good *descriptor* and a bad
*intervention target*: ρ = 0.762 with judge score, and Δ = 0 when you move it
deliberately. Correlational ranking metrics do not survive being optimised.

## Finding 11 — the real effect, on a metric that can see it (POST-HOC)

`citation_expected_recall` = fraction of expected paths actually cited.

| population | cf4 | cf10 | Δ | 95% CI | improved/worsened |
|---|---|---|---|---|---|
| all cases (n=100) | 0.610 | 0.665 | **+0.055** | [+0.009, +0.101] | 11 / 3 |
| ≥2 expected paths (n=62) | 0.548 | 0.605 | +0.056 | [−0.004, +0.117] | 9 / 3 |
| the 14 bundle-flip cases | 0.464 | 0.750 | +0.286 | — | 6 of 14 went 0.50→1.00 |

So the treatment *did* cause the model to cite the newly-available second file
— in roughly 43% of the cases where that file became available.

**This is a post-hoc metric and must be labelled as such.** The pre-committed
criterion returned null; this one was selected after seeing that result,
because it is definitionally sensitive to the treatment. The overall CI barely
excludes zero and the multi-path CI includes it. Treat as a hypothesis to
confirm, not as an established win.

## Verdict

Not a clean promotion. Costs 8.5% latency, delivers a confirmed mechanism, a
null on the pre-committed outcome, and a marginal post-hoc gain. The honest
summary is: **widening the window puts the right files in front of the model,
and the model uses the extra file less than half the time.**

## Consequences for H16

H16's arms b and d assume the chain
`more depth → better candidate bundle → better answers`.
H15 just tested the second half of that chain in isolation and got ~43%
conversion at best. Depth is still worth testing — it is cheap, and it attacks
`candidate_bundle_complete` = 0.620, the binding ceiling H15 could not pass —
but the expected effect size should be discounted accordingly.

**Metric commitment for H16, fixed now, before any arm runs:**
primary = `citation_expected_recall`; guardrail = `citation_fabricated_rate`;
mechanism check = `candidate_bundle_complete` (not `context_bundle_complete`,
which is now saturated at the candidate ceiling). `answer_grounded` is
retained for continuity but is **not** a ranking criterion for multi-path
interventions, per Finding 9.

## Open

- Rejudge (qwen35-9b) was still running when this was written; judge numbers
  are not in this record and are not needed for the verdict above.
- The deeper question H15 raises and does not answer: when the model has the
  expected file and still does not cite it, is that a prompt problem, a
  context-ordering problem, or a capability limit of a 4B model? That is a
  better next hypothesis than more retrieval depth if H16's arms come back
  weak.
