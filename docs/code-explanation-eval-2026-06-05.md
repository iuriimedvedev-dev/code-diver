# Code Explanation Evaluation

Updated: 2026-06-05.

## Why This Exists

The retrieval benchmarks answer only one question: can Code Diver find the right
file or code item?

The assignment goal is broader: the tool must also explain code. That means we
need a second evaluation lane that measures whether the model can turn source
code into a useful developer-facing explanation.

## Public Benchmark

The first supported public benchmark is:

| Field | Value |
| --- | --- |
| CLI name | `codexglue-code-to-text-python` |
| Source dataset | `google/code_x_glue_ct_code_to_text` |
| Split | Python `test` slice |
| Task shape | Python function/code -> natural-language explanation |
| Reference | Original docstring |
| Local artifact | `.code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl` |

This is intentionally different from the CodeSearchNet retrieval benchmark. It
does not test whether we found the right file. It tests whether the configured
generation model can explain a provided code snippet.

## Command

The command is advanced because the public assignment surface remains
`index`, `search`, and `evaluate`.

```bash
uv run code-diver --help-all evaluate-explanations \
  --benchmark codexglue-code-to-text-python \
  --cases 50 \
  --yes \
  --judge \
  --judge-prompt prompts/code-explanation-judge.md \
  --judge-model gemini-3.1-flash-lite
```

Use a separate judge config when generation and judging should use different
providers:

```bash
uv run code-diver --config configs/local-explainer.yml --help-all evaluate-explanations \
  --cases 50 \
  --yes \
  --judge \
  --judge-prompt prompts/code-explanation-judge.md \
  --judge-config configs/gemini-judge.yml \
  --judge-model gemini-3.1-flash-lite
```

The command asks before preparing a missing benchmark unless `--yes` is passed.
It writes a full JSON report with every case, prediction, reference, metrics,
judge rationale, duration, and token usage.

## Metrics

Local deterministic metrics:

| Metric | Meaning |
| --- | --- |
| `token_precision` | Fraction of generated tokens that overlap the reference docstring. |
| `token_recall` | Fraction of reference tokens covered by the generated explanation. |
| `token_f1` | Harmonic mean of token precision and recall. |
| `key_token_*` | Same overlap after removing common stop words. This is less sensitive to filler phrasing. |
| `bigram_*` | Two-token phrase overlap. This is stricter and catches whether important phrases survive. |
| `prediction_tokens` | Mean generated explanation length. |
| `reference_tokens` | Mean reference docstring length. |

Optional LLM-as-judge metrics are computed from an editable questionnaire prompt.
The default prompt is [prompts/code-explanation-judge.md](../prompts/code-explanation-judge.md).
The model returns a structured answer for each criterion, including a score,
short verdict, and evidence. Code Diver then computes the weighted final score
deterministically.

| Metric | Scale | Meaning |
| --- | --- | --- |
| `judge_purpose_accuracy` | 0-4 | Correctly identifies what the code is for. |
| `judge_behavior_accuracy` | 0-4 | Accurately describes control flow, transformations, branches, loops, calls, and returned behavior. |
| `judge_api_contract` | 0-4 | Correctly covers inputs, outputs, side effects, and visible errors/exceptions. |
| `judge_groundedness` | 0-4 | Important claims are supported by code/reference; hallucinations are penalized. |
| `judge_specificity` | 0-4 | Mentions concrete names and concepts from the code. |
| `judge_completeness` | 0-4 | Covers the important behavior a developer needs to understand or modify the code. |
| `judge_clarity` | 0-4 | Concise, readable, and organized for a developer. |
| `judge_overall` | 0-5 | Weighted final score computed by Code Diver from the questionnaire. |

Default weights:

| Criterion | Weight |
| --- | ---: |
| `purpose_accuracy` | `0.18` |
| `behavior_accuracy` | `0.22` |
| `api_contract` | `0.15` |
| `groundedness` | `0.18` |
| `specificity` | `0.12` |
| `completeness` | `0.10` |
| `clarity` | `0.05` |

## Known Limitations

- CodeXGLUE code-to-text is function-level summarization, not full repository
  exploration. It does not test multi-file reasoning, search quality, or whether
  citations point to the right lines.
- Docstrings are useful references but not perfect ground truth. Some are too
  terse, outdated, or describe API contracts not visible in the function body.
- Token overlap metrics are cheap and reproducible, but they penalize correct
  paraphrases. The judge rubric exists because explanation quality is semantic.
- LLM-as-judge can be biased. Use the same judge model/config/prompt across
  comparisons and keep the full JSON report for auditability.

## Next Layer

The next explanation benchmark should be repo-level:

1. Build or load an H5 index for a repository.
2. Ask natural-language code-exploration questions.
3. Let the Search agent retrieve and inspect code.
4. Judge the final answer for correctness, completeness, specificity,
   groundedness, and citation quality.

That repo-level lane will connect retrieval quality to actual user-facing
explanations. The CodeXGLUE lane gives us the first clean, public, reproducible
explainer metric before that larger eval is built.

## Initial Smoke Result

Smoke command:

```bash
uv run code-diver --help-all evaluate-explanations \
  --cases 1 \
  --yes \
  --judge \
  --judge-prompt prompts/code-explanation-judge.md \
  --judge-model gemini-3.1-flash-lite \
  --output .code-diver/reports/codexglue-code-explanation-questionnaire-smoke.json \
  --json
```

Result:

| Metric | Value |
| --- | ---: |
| `cases` | `1` |
| `token_f1` | `0.125` |
| `key_token_f1` | `0.151` |
| `bigram_f1` | `0.000` |
| `judge_purpose_accuracy` | `4.000` |
| `judge_behavior_accuracy` | `4.000` |
| `judge_api_contract` | `4.000` |
| `judge_groundedness` | `4.000` |
| `judge_specificity` | `4.000` |
| `judge_completeness` | `4.000` |
| `judge_clarity` | `4.000` |
| `judge_overall` | `5.000` |
| generation tokens | `482` |
| judge tokens | `1556` |
| duration | `2799 ms` |

This single case demonstrates why explanation eval needs both deterministic
overlap and semantic judge metrics. The reference docstring is only nine tokens,
so phrase overlap is low even though the questionnaire judge marks every
criterion as excellent and records concrete evidence: XML parsing, `durl`
iteration, URL extraction, returned list, and no unsupported claims.

## Local Judge Smoke

Gemma 4 E4B was tested as a local questionnaire judge while keeping Gemini 3.1
Flash Lite as the explanation generator:

```bash
uv run code-diver --help-all evaluate-explanations \
  --cases 1 \
  --yes \
  --judge \
  --judge-prompt prompts/code-explanation-judge.md \
  --judge-config configs/explanation-judge-gemma4-e4b.yml \
  --output .code-diver/reports/codexglue-code-explanation-gemma4-e4b-judge-smoke.json \
  --json
```

The first attempted `mlx-community/gemma-4-e4b-it-OptiQ-4bit` runtime failed in
`mlx_vlm.server` with missing vision-tower parameters. The working local judge
config uses `mlx-community/gemma-4-e4b-it-4bit` on `127.0.0.1:8013`.

| Metric | Gemini Lite judge | Gemma 4 E4B local judge |
| --- | ---: | ---: |
| `cases` | `1` | `1` |
| `judge_purpose_accuracy` | `4.000` | `4.000` |
| `judge_behavior_accuracy` | `4.000` | `4.000` |
| `judge_api_contract` | `4.000` | `3.000` |
| `judge_groundedness` | `4.000` | `4.000` |
| `judge_specificity` | `4.000` | `3.000` |
| `judge_completeness` | `4.000` | `3.000` |
| `judge_clarity` | `4.000` | `4.000` |
| `judge_overall` | `5.000` | `4.538` |
| judge tokens | `1556` | `1673` |
| total duration | `2799 ms` | `8085 ms` |

The local judge was stricter and more diagnostic on this case: it did not mark
everything perfect, and it explained the small deductions around API contract,
specificity, and completeness. The tradeoff is latency. This needs a larger
sample before treating Gemma E4B as a judge default.
