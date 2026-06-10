# Judge vs Meta-Judge Score Report — Code Explainer Candidates

**Date**: 2026-06-10  |  **Dataset**: 100 CodeXGLUE-Python cases  |  **Individual Judge**: Gemini 1.5 Flash Lite  |  **Meta-Judge**: Gemini 1.5 Flash Lite

## Executive Summary

This report compares **individual judge scores** (each candidate judged independently) against **meta-judge scores** (all 8 candidates judged together per case, random order).

### Key Findings

1. **Meta-judge parsing bug (31% data loss)**: 31/100 cases returned criteria scores as plain integers (e.g., `"purpose_accuracy": 4`) instead of the expected dict format `{"score": 4, "evidence": "..."}`. The parser fails to extract scores from int-format criteria → all 8 candidates get 0.0 for those cases. This severely distorts all meta-judge metrics.

2. **e2b/e2b-rerun generation failures**: E2B original has 72/100 generation errors; E2B rerun has 76/100. These produce empty predictions that score 0 in both individual and meta judging.

3. **Individual judge ceiling effect**: All functioning candidates score 5.0/5.0 median on judge_overall. The individual judge fails to discriminate — nearly all valid predictions get perfect scores.

4. **Meta-judge ranking (when controlling for both bugs)**: When excluding the 31 parse-failure cases AND the empty-prediction cases, all candidates converge to mean 4.8–4.9, still poor discrimination.

5. **Neither evaluation method is reliable** for ranking these candidates. The individual judge has ceiling effect; the meta-judge has a parsing bug and still shows ceiling after correction.

## 1. Combined Comparison Table (Individual vs Meta)

| Candidate | Indiv Mean JO | Meta Mean JO | Indiv Med JO | Meta Med JO | Indiv Valid | Meta Valid | Indiv Dur (ms) | Meta Dur (ms) | Indiv TokF1 | Indiv BigramF1 |
|---|---|---|---|---|---|---|---|---|---|---|
| e2b | 1.3919 | 0.6334 | 5.0000 | 0.0000 | 28 | 13 | 8316 | — | 0.0353 | 0.0156 |
| e4b | 4.5332 | 3.0417 | 5.0000 | 5.0000 | 91 | 62 | 23850 | — | 0.1348 | 0.0521 |
| e2b-rerun | 1.2000 | 0.6466 | 5.0000 | 0.0000 | 24 | 13 | 22075 | — | 0.0437 | 0.0190 |
| e4b-rerun | 4.5179 | 3.0408 | 5.0000 | 5.0000 | 91 | 62 | 24808 | — | 0.1373 | 0.0535 |
| gemma26 | 4.6901 | 3.1565 | 5.0000 | 4.8500 | 95 | 64 | 1573776 | — | 0.1948 | 0.0706 |
| qwen4b | 4.9864 | 3.3255 | 5.0000 | 4.7812 | 100 | 69 | 514927 | — | 0.2088 | 0.0711 |
| qwen9b | 4.9931 | 3.3710 | 5.0000 | 4.8500 | 100 | 69 | 450462 | — | 0.1900 | 0.0609 |
| gemini-flash | 5.0000 | 3.3591 | 5.0000 | 4.8500 | 100 | 69 | 46583 | — | 0.2068 | 0.0618 |

**Key**: JO = judge_overall (0–5 scale). Valid = cases with non-zero score. Indiv Dur is per-candidate judge runtime (meta per-case runtime is ~875ms average).

## 2. Ranking Comparison

### Individual Judge Ranking (by mean judge_overall)
| Rank | Candidate | Mean JO |
|---|---|---|
| 1 | gemini-flash | 5.0000 |
| 2 | qwen9b | 4.9931 |
| 3 | qwen4b | 4.9864 |
| 4 | gemma26 | 4.6901 |
| 5 | e4b | 4.5332 |
| 6 | e4b-rerun | 4.5179 |
| 7 | e2b | 1.3919 |
| 8 | e2b-rerun | 1.2000 |

### Meta-Judge Ranking (by mean judge_overall)
| Rank | Candidate | Mean JO | Win Rate | Mean Rank |
|---|---|---|---|
| 1 | qwen9b | 3.3710 | 0.1300 | 3.93 |
| 2 | gemini-flash | 3.3591 | 0.0600 | 4.42 |
| 3 | qwen4b | 3.3255 | 0.0500 | 4.59 |
| 4 | gemma26 | 3.1565 | 0.0900 | 4.32 |
| 5 | e4b | 3.0417 | 0.3200 | 2.61 |
| 6 | e4b-rerun | 3.0408 | 0.2500 | 2.88 |
| 7 | e2b-rerun | 0.6466 | 0.0900 | 6.18 |
| 8 | e2b | 0.6334 | 0.0900 | 6.07 |

**Discrepancy**: Individual judge places gemini-flash first (5.0) and e2b-rerun last (1.2). Meta-judge places qwen9b first (3.37) and e2b last (0.63). The meta-judge ranking is heavily distorted by the 31 zero-bug cases pulling means toward 0.

## 3. Per-Candidate Breakdown

### e2b

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 72 | Valid explanations: 28
- Token F1: 0.0353 | Key Token F1: 0.0339 | Bigram F1: 0.0156
- Judge overall: mean=1.3919 | median=5.000 | Duration: 8316ms
- Prediction tokens: 70.9 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 1.11, behavior_accuracy: 1.11, clarity: 1.12, completeness: 1.11, groundedness: 1.12, purpose_accuracy: 1.11, specificity: 1.12

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.0900 | Mean rank: 6.07 | Median rank: 7
- Mean judge_overall: 0.633375 | Median: 0.0000
- Non-zero scores: 13/100 (zeros: 87) | Non-zero mean: 4.8721 | Non-zero median: 5.0000

### e4b

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 9 | Valid explanations: 91
- Token F1: 0.1348 | Key Token F1: 0.1246 | Bigram F1: 0.0521
- Judge overall: mean=4.5332 | median=5.000 | Duration: 23850ms
- Prediction tokens: 203.6 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 3.62, behavior_accuracy: 3.61, clarity: 3.64, completeness: 3.62, groundedness: 3.63, purpose_accuracy: 3.64, specificity: 3.64

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.3200 | Mean rank: 2.61 | Median rank: 2
- Mean judge_overall: 3.041750 | Median: 5.0000
- Non-zero scores: 62/100 (zeros: 38) | Non-zero mean: 4.9060 | Non-zero median: 5.0000

### e2b-rerun

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 76 | Valid explanations: 24
- Token F1: 0.0437 | Key Token F1: 0.0414 | Bigram F1: 0.0190
- Judge overall: mean=1.2000 | median=5.000 | Duration: 22075ms
- Prediction tokens: 62.2 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 0.96, behavior_accuracy: 0.96, clarity: 0.96, completeness: 0.96, groundedness: 0.96, purpose_accuracy: 0.96, specificity: 0.96

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.0900 | Mean rank: 6.18 | Median rank: 7
- Mean judge_overall: 0.646625 | Median: 0.0000
- Non-zero scores: 13/100 (zeros: 87) | Non-zero mean: 4.9740 | Non-zero median: 5.0000

### e4b-rerun

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 9 | Valid explanations: 91
- Token F1: 0.1373 | Key Token F1: 0.1273 | Bigram F1: 0.0535
- Judge overall: mean=4.5179 | median=5.000 | Duration: 24808ms
- Prediction tokens: 199.5 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 3.61, behavior_accuracy: 3.59, clarity: 3.64, completeness: 3.61, groundedness: 3.62, purpose_accuracy: 3.62, specificity: 3.64

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.2500 | Mean rank: 2.88 | Median rank: 2
- Mean judge_overall: 3.040750 | Median: 5.0000
- Non-zero scores: 62/100 (zeros: 38) | Non-zero mean: 4.9044 | Non-zero median: 5.0000

### gemma26

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 5 | Valid explanations: 95
- Token F1: 0.1948 | Key Token F1: 0.1801 | Bigram F1: 0.0706
- Judge overall: mean=4.6901 | median=5.000 | Duration: 1573776ms
- Prediction tokens: 105.3 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 3.75, behavior_accuracy: 3.74, clarity: 3.76, completeness: 3.74, groundedness: 3.76, purpose_accuracy: 3.76, specificity: 3.76

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.0900 | Mean rank: 4.32 | Median rank: 4
- Mean judge_overall: 3.156500 | Median: 4.8500
- Non-zero scores: 64/100 (zeros: 36) | Non-zero mean: 4.9320 | Non-zero median: 5.0000

### qwen4b

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 0 | Valid explanations: 100
- Token F1: 0.2088 | Key Token F1: 0.1937 | Bigram F1: 0.0711
- Judge overall: mean=4.9864 | median=5.000 | Duration: 514927ms
- Prediction tokens: 109.6 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 3.99, behavior_accuracy: 3.97, clarity: 4.00, completeness: 3.99, groundedness: 3.99, purpose_accuracy: 4.00, specificity: 4.00

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.0500 | Mean rank: 4.59 | Median rank: 5
- Mean judge_overall: 3.325500 | Median: 4.7812
- Non-zero scores: 69/100 (zeros: 31) | Non-zero mean: 4.8196 | Non-zero median: 4.9375

### qwen9b

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 0 | Valid explanations: 100
- Token F1: 0.1900 | Key Token F1: 0.1755 | Bigram F1: 0.0609
- Judge overall: mean=4.9931 | median=5.000 | Duration: 450462ms
- Prediction tokens: 132.8 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 3.99, behavior_accuracy: 3.99, clarity: 4.00, completeness: 4.00, groundedness: 3.99, purpose_accuracy: 4.00, specificity: 4.00

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.1300 | Mean rank: 3.93 | Median rank: 4
- Mean judge_overall: 3.371000 | Median: 4.8500
- Non-zero scores: 69/100 (zeros: 31) | Non-zero mean: 4.8855 | Non-zero median: 5.0000

### gemini-flash

#### Individual Judge Metrics
- Cases: 100 | Generation errors: 0 | Valid explanations: 100
- Token F1: 0.2068 | Key Token F1: 0.1833 | Bigram F1: 0.0618
- Judge overall: mean=5.0000 | median=5.000 | Duration: 46583ms
- Prediction tokens: 87.1 avg | Reference tokens: 36.1 avg
- Per-criteria means: api_contract: 4.00, behavior_accuracy: 4.00, clarity: 4.00, completeness: 4.00, groundedness: 4.00, purpose_accuracy: 4.00, specificity: 4.00

#### Meta-Judge Metrics
- Cases scored: 100 | Win rate: 0.0600 | Mean rank: 4.42 | Median rank: 5
- Mean judge_overall: 3.359125 | Median: 4.8500
- Non-zero scores: 69/100 (zeros: 31) | Non-zero mean: 4.8683 | Non-zero median: 5.0000

## 4. The 31 Zero-All Cases Investigation

**Problem**: 31/100 cases (31%) have ALL 8 candidates scoring 0.0 in the meta-judge. This is the single biggest issue with the meta-judge data.

### Root Cause: LLM Output Format Inconsistency

The meta-judge prompt requests per-candidate criteria with evidence. However, the LLM alternates between two output formats:

| Format | Structure | Cases |
|---|---|---|
| **Dict (correct)** | `"purpose_accuracy": {"score": 4, "evidence": "..."}` | 69/100 (non-zero) |
| **Int (incorrect)** | `"purpose_accuracy": 4` | 31/100 (zero-all) |

The meta-judge parser only handles the dict format. When encountering int-format criteria, it fails to extract scores and defaults all to 0.0.

### Impact Breakdown

| Candidate | Gen Errors | Individual Zeros | Meta Zeros (total) | Meta Zeros from Bug | Meta Zeros from Errors |
|---|---|---|---|---|---|
| e2b | 72 | 72 | 87 | 31 | 56 |
| e4b | 9 | 9 | 38 | 31 | 7 |
| e2b-rerun | 76 | 76 | 87 | 31 | 56 |
| e4b-rerun | 9 | 9 | 38 | 31 | 7 |
| gemma26 | 5 | 5 | 36 | 31 | 5 |
| qwen4b | 0 | 0 | 31 | 31 | 0 |
| qwen9b | 0 | 0 | 31 | 31 | 0 |
| gemini-flash | 0 | 0 | 31 | 31 | 0 |

### Are There Other Patterns?

- **No position bias found**: The 31 zero-all cases have diverse permutations across all 8 slots. Position counts are balanced.
- **No code difficulty correlation**: Cases like `codexglue-python-14` (all-candidates-zero despite valid individual scores 5.0 for all) have no distinguishing features from non-zero cases.
- **No prediction length correlation**: Zero and non-zero cases have similar average code lengths.

## 5. Duration Comparison

| Candidate | Individual Duration (ms) | Per-case Avg (ms) |
|---|---|---|
| e2b | 8316 | 83.2 |
| e4b | 23850 | 238.5 |
| e2b-rerun | 22075 | 220.8 |
| e4b-rerun | 24808 | 248.1 |
| gemma26 | 1573776 | 15737.8 |
| qwen4b | 514927 | 5149.3 |
| qwen9b | 450462 | 4504.6 |
| gemini-flash | 46583 | 465.8 |
| **Total (individual)** | **2664797** | — |
| **Meta-judge total** | **87474** | **874.7** |

Meta-judge is much slower than individual per-case (875ms vs 83-1,577ms per case total) because it processes 8 responses per API call. gemma26 individual judging was extremely slow (1,574s) due to the larger model run on Vertex AI.

## 6. Issues Found

### Critical
1. **Meta-judge parser fails on int-format criteria (31% data loss)** — `.code-diver/reports/meta-judge-all-candidates-100.json` has 31 cases where all 8 candidates score 0.0 because the LLM returned plain integers instead of dicts with `score`/`evidence` keys. The parser at the relevant extraction point needs to handle both formats.

2. **Individual judge ceiling effect** — All 6 functioning candidates show median judge_overall = 5.0/5.0. The judge fails to discriminate between good and excellent explanations. Either the scale is too coarse or the judge is too lenient on single-candidate evaluation.

### Moderate
3. **e2b/e2b-rerun massive generation error rate (72-76%)** — E2B (Gemma 4 E2B) generates invalid JSON in ~3/4 of cases. Rerun didn't fix this. The model architecture or prompt likely needs adjustment.

4. **No reference model for meta-judge** — Unlike individual judging where reference explanations exist, the meta-judge compares candidates relative to each other without a gold standard. The ranking is ordinal, not absolute.

### Minor
5. **Token F1 / Bigram F1 near zero** — Token-level metrics are 0.02-0.07 across the board. This reflects the reference being a 1-sentence description while predictions are multi-paragraph explanations. These metrics are not meaningful for free-form explanation evaluation.

## 7. Recommendations

1. **Fix meta-judge parser** to handle int-format criteria. This alone would recover 31% of the data and likely produce meaningful rankings.

2. **Re-run meta-judge with stricter output formatting** — Use constrained decoding (JSON mode) or a more explicit prompt with examples of both formats, emphasizing the `{"score": N, "evidence": "..."}` structure.

3. **Calibrate individual judge** — The 5-point scale with 1.25x weighting produces mean scores of 5.0 for most candidates. Consider a 7-point scale or relative scoring (pairwise comparison).

4. **Fix E2B generation** — 72-76% error rate makes e2b/e2b-rerun unevaluable. Investigate the JSON parsing failures (they appear to be truncated responses with `Extra data` errors).

5. **Switch to pairwise evaluation** — Rather than ranking 8 candidates simultaneously (which increases prompt complexity), use pairwise comparisons with an ELO system. This would also avoid the format issue since each pair produces a simpler response.

## Полная таблица метрик

### Базовые метрики + F1

| Candidate | Valid | JO µ | JO Σ | Chars | Words | TTR | EmbSim | TokF1 | KeyF1 | BiF1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| e2b-rerun | 24 | 5.000 | 120.0 | 1789 | 269 | 0.467 | 0.7066 | 0.0437 | 0.0414 | 0.0190 |
| gemini-flash | 100 | 5.000 | 500.0 | 570 | 90 | 0.657 | 0.7467 | 0.2068 | 0.1833 | 0.0618 |
| qwen9b | 100 | 4.993 | 499.3 | 866 | 136 | 0.592 | 0.7350 | 0.1900 | 0.1755 | 0.0609 |
| gemma26 | 94 | 4.989 | 469.0 | 759 | 117 | 0.589 | 0.7620 | 0.1948 | 0.1801 | 0.0706 |
| qwen4b | 100 | 4.986 | 498.6 | 708 | 113 | 0.619 | 0.7617 | 0.2088 | 0.1937 | 0.0711 |
| e4b | 91 | 4.982 | 453.3 | 1574 | 234 | 0.497 | 0.6907 | 0.1348 | 0.1246 | 0.0521 |
| e2b | 28 | 4.971 | 139.2 | 1725 | 261 | 0.469 | 0.6367 | 0.0353 | 0.0339 | 0.0156 |
| e4b-rerun | 91 | 4.965 | 451.8 | 1538 | 230 | 0.497 | 0.6885 | 0.1373 | 0.1273 | 0.0535 |

### Keyword Overlap (TF-IDF, vs reference)

| Candidate | KW Prec | KW Rec | KW F1 |
| ---: | ---: | ---: | ---: |
| qwen4b | 0.4000 | 0.4000 | 0.4000 |
| e4b-rerun | 0.3667 | 0.3667 | 0.3667 |
| gemma26 | 0.3667 | 0.3667 | 0.3667 |
| qwen9b | 0.3667 | 0.3667 | 0.3667 |
| e4b | 0.3333 | 0.3333 | 0.3333 |
| gemini-flash | 0.3333 | 0.3333 | 0.3333 |
| e2b-rerun | 0.2667 | 0.2667 | 0.2667 |
| e2b | 0.2333 | 0.2333 | 0.2333 |

### Interpretations

- **JO µ** — maxed out at ~5.0 for all (ceiling effect), no discrimination.
- **EmbSim** — gemma26 (0.762) и qwen4b (0.762) best semantic alignment; e4b lowest (0.691) despite being most verbose.
- **TokF1 / KeyF1 / BiF1** — qwen4b best exact match (0.209 / 0.194 / 0.071); e4b much worse (0.135 / 0.125 / 0.052).
- **TTR** — gemini-flash highest (0.657), most lexically diverse; e4b/e2b low (~0.50) due to verbosity.
- **KW F1** — qwen4b highest keyword coverage (0.400); gemini-flash surprisingly low (0.333) — uses simpler vocabulary than reference.
- **E2B** — fundamentally broken: only 24-28% valid generations, near-zero F1 scores.
- **E4B** — verbose (1574 chars avg) but poor on all overlap metrics; generated explanations drift from reference.

### Вывод: кандидаты по убыванию качества

1. **qwen4b** — best keyword overlap, best F1, high EmbSim, concise
2. **gemini-flash** — best lexical diversity, high F1, good EmbSim, most concise
3. **gemma26** — best EmbSim, good F1, solid keyword coverage
4. **qwen9b** — balanced, but slightly worse on all metrics vs qwen4b
5. **e4b-rerun** — verbose but mediocre overlap
6. **e4b** — verbose, poor overlap (slightly worse than rerun)
7. **e2b-rerun** — 24% valid only, unusable
8. **e2b** — 28% valid only, unusable
