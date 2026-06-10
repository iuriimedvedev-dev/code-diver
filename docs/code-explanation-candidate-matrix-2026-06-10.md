# Code Explanation Candidate Matrix - 2026-06-10

## Scope

This report compares **models as code explainers** only.

Fixed setup:

| Axis | Value |
| --- | --- |
| Dataset | CodeXGLUE code-to-text Python |
| Cases | `100` |
| Saved explanation field | `results[].prediction` |
| Judge | Vertex `gemini-3.1-flash-lite` |
| Judge prompt | `prompts/code-explanation-judge.md` |
| Judge mode | post-hoc rejudge of saved explanations; no explanation regeneration |
| Score scale | rubric scores `0..4`, `judge_overall` normalized to `0..5` |

Do not mix this table with H10/H13/H14 Protogen answer reports. Those are
end-to-end retrieval/context/answer evaluations, not isolated explainer-model
benchmarks.

## Saved Explanation Inputs

The candidate explanations were already saved in these reports:

```text
.code-diver/reports/h6-1-local-matrix-ex1-e2b-explain-e4b-judge-100.json
.code-diver/reports/h6-1-local-matrix-ex2-e4b-explain-e4b-judge-100.json
.code-diver/reports/h6-1-local-matrix-ex3-e2b-explain-qwen9b-judge-100.json
.code-diver/reports/h6-1-local-matrix-ex4-e4b-explain-qwen9b-judge-100.json
```

For successful generations, the explanation text is in `results[].prediction`.
Failed generations are preserved as rows with `error`/`raw_prediction` and count
as zero-quality rows in the aggregate, because an explainer that does not return
a valid explanation is not usable.

## Unified Judge Outputs

These reports were generated from the saved explanations with one judge:

```text
.code-diver/reports/code-explainer-ex1-gemma-e2b-vertex-gemini31-flash-lite-judge-100.json
.code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json
.code-diver/reports/code-explainer-ex3-gemma-e2b-rerun-vertex-gemini31-flash-lite-judge-100.json
.code-diver/reports/code-explainer-ex4-gemma-e4b-rerun-vertex-gemini31-flash-lite-judge-100.json
```

All four clean rejudge runs completed with `judge_error_count = 0`.

## Final Matrix

| Candidate | Source report | Cases | Valid explanations | Gen errors | Judge errors | Judge calls | Judge overall | Purpose | Behavior | API | Grounded | Specificity | Complete | Clarity | Token F1 | Key F1 | Bigram F1 | Mean tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemma 4 E2B | `h6-1-local-matrix-ex1-e2b-explain-e4b-judge-100.json` | 100 | 28 | 72 | 0 | 28 | 1.392 | 1.110 | 1.110 | 1.110 | 1.120 | 1.120 | 1.110 | 1.120 | 0.035 | 0.034 | 0.016 | 70.9 |
| Gemma 4 E4B | `h6-1-local-matrix-ex2-e4b-explain-e4b-judge-100.json` | 100 | 91 | 9 | 0 | 91 | 4.533 | 3.640 | 3.610 | 3.620 | 3.630 | 3.640 | 3.620 | 3.640 | 0.135 | 0.125 | 0.052 | 203.6 |
| Gemma 4 E2B rerun | `h6-1-local-matrix-ex3-e2b-explain-qwen9b-judge-100.json` | 100 | 24 | 76 | 0 | 24 | 1.200 | 0.960 | 0.960 | 0.960 | 0.960 | 0.960 | 0.960 | 0.960 | 0.044 | 0.041 | 0.019 | 62.2 |
| Gemma 4 E4B rerun | `h6-1-local-matrix-ex4-e4b-explain-qwen9b-judge-100.json` | 100 | 91 | 9 | 0 | 91 | 4.518 | 3.620 | 3.590 | 3.610 | 3.620 | 3.640 | 3.610 | 3.640 | 0.137 | 0.127 | 0.054 | 199.5 |

## Ranking

| Rank | Model | Best judge overall | Mean judge overall across saved runs | Reliability | Decision |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | Gemma 4 E4B | 4.533 | 4.526 | 91/100 valid explanations in both saved runs | Best current local code explainer. |
| 2 | Gemma 4 E2B | 1.392 | 1.296 | 24-28/100 valid explanations | Reject for code explanation. |

## Interpretation

Gemma 4 E4B is the clear winner among saved explainer candidates. It is stable
across two saved 100-case runs on the same dataset, and the same Vertex judge
scores both runs around `4.52-4.53` overall.

Gemma 4 E2B is not viable for this role under the current strict JSON
explanation contract. The issue is not subtle semantic quality; it fails to
produce valid explanations in most cases (`72-76` generation errors per 100).

Overlap metrics agree with the judge ranking but should not be treated as the
primary quality metric. The judge is the selector here because explanation
quality is semantic and the CodeXGLUE reference docstrings are often short.

## What Is Still Missing

Current saved isolated-explainer data covers only:

```text
Gemma 4 E2B
Gemma 4 E4B
```

There is no saved 100-case CodeXGLUE isolated-explanation run for:

```text
Gemma 4 26B
Qwen3.5 9B as explainer
Gemini/Vertex as explainer
OpenAI/other API explainer
```

H10/H13/H14 reports do contain generated developer-facing answers, but they are
not comparable here because they include retrieval, context selection, citations,
and repository-answer behavior. If Gemma 26B should compete as a pure explainer,
it needs an `evaluate-explanations --cases 100` run on the same CodeXGLUE dataset
and then the same Vertex rejudge.

## Reproduction

Example rejudge command:

```bash
uv run python scripts/rejudge_explanation_report.py \
  .code-diver/reports/h6-1-local-matrix-ex2-e4b-explain-e4b-judge-100.json \
  --dataset .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl \
  --judge-config configs/explanation-judge-vertex-gemini31-flash-lite.yml \
  --output .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json \
  --partial-output .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.partial.json \
  --workers 8
```

Supporting implementation:

```text
configs/explanation-judge-vertex-gemini31-flash-lite.yml
scripts/rejudge_explanation_report.py
```
