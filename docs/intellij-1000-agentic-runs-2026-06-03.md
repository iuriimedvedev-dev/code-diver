# IntelliJ 1000-Case Agentic Runs - 2026-06-03

This report is the final research slice for the 2026-06-03 IntelliJ agentic-search investigation. It separates valid search-quality metrics from invalid/degraded runs so the next engineering pass does not optimize against corrupted numbers.

The conclusion is intentionally conservative:

```text
Pure H3 is the strong baseline.
Agentic H3 is currently worse, more expensive, and slower.
Gemini 3.5 Flash is a quality ceiling/oracle, not a routine experiment model.
Gemini 3.1 Flash Lite is useful as a cheap API reranker/entrypoint.
Qwen3.5 4B local is a viable local candidate, but too slow in the current agentic loop.
```

## Dataset

All active runs use:

```text
datasets/intellij_eval_1000.answer_sets.jsonl
```

The run-specific config is saved at:

```text
.code-diver/reports/agentic-h3-1000/intellij-postrank-h3-manifest-answer-sets.yml
```

It differs from `configs/intellij-postrank-h3-manifest.yml` only by using the answer-set dataset and a separate trace artifact.

## Validity Rules

Use these rules when reading the tables below:

| Status | Meaning | Use for quality comparison? |
| --- | --- | --- |
| Valid | Completed on the intended dataset with `degraded_cases = 0`, no infrastructure failure, and no failed cases counted as misses. | Yes |
| Degraded partial | Incomplete and/or `degraded = true`; useful for operational debugging and directional signal only. | No |
| Invalid | Infrastructure failure, interrupted authentication, zero-byte output, or failed cases mixed into metrics. | No |

The runner must become fail-fast for research-quality gates. A result with many infrastructure failures should not silently become a low Hit@10 search-quality number.

## Run Inventory

| Screen | Setup | Output | Notes |
| --- | --- | --- | --- |
| `cdv-1000-pure-h3-gemini-lite` | Pure H3 deterministic branch C + Gemini 3.1 Flash Lite rerank | `.code-diver/reports/agentic-h3-1000/partials-pure-h3-gemini-lite/h3_manifest_union_rerank_gemini_flash_lite.partial.json` | Degraded partial at 800/1000. Good directional baseline, not a valid final quality metric. |
| `cdv-1000-agentic-gemini-lite` | Agentic H3 bounded tools + Gemini 3.1 Flash Lite | `.code-diver/reports/agentic-h3-1000/intellij-1000-agentic-h3-gemini-lite-bounded.json` | Invalid: ADC reauthentication failures are counted as search misses. |
| `cdv-1000-agentic-qwen35` | Agentic H3 bounded tools + local Qwen3.5 4B OptiQ 4bit | `.code-diver/reports/agentic-h3-1000/intellij-1000-agentic-h3-qwen35-bounded.json` | Invalid: zero-byte artifact. Use only the saved 100-case calibration for Qwen conclusions. |

Gemini 3.5 Flash is intentionally not running because it is too expensive for the current loop.

## Commands

Pure H3 baseline:

```bash
uv run python scripts/run_postrank_h2_deterministic.py \
  --config .code-diver/reports/agentic-h3-1000/intellij-postrank-h3-manifest-answer-sets.yml \
  --dataset datasets/intellij_eval_1000.answer_sets.jsonl \
  --cases 1000 \
  --limit 10 \
  --hypothesis h3_manifest_union_rerank_gemini_flash_lite \
  --progress-every 25 \
  --partial-dir .code-diver/reports/agentic-h3-1000/partials-pure-h3-gemini-lite \
  --output .code-diver/reports/agentic-h3-1000/intellij-1000-pure-h3-gemini-lite.json \
  --report .code-diver/reports/agentic-h3-1000/intellij-1000-pure-h3-gemini-lite.html
```

Agentic Gemini Lite:

```bash
uv run code-diver \
  --config .code-diver/reports/agentic-h3-1000/intellij-postrank-h3-manifest-answer-sets.yml \
  evaluate-search-tools \
  --dataset datasets/intellij_eval_1000.answer_sets.jsonl \
  --limit 10 \
  --hypothesis ai_h3_agentic_gemini_flash_lite \
  --json
```

Agentic Qwen:

```bash
uv run code-diver \
  --config .code-diver/reports/agentic-h3-1000/intellij-postrank-h3-manifest-answer-sets.yml \
  evaluate-search-tools \
  --dataset datasets/intellij_eval_1000.answer_sets.jsonl \
  --limit 10 \
  --hypothesis ai_h3_agentic_qwen35_4b \
  --json
```

## 100-Case Calibration

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | nDCG@10 | MAP@10 | Mean ms | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pure H3 + Gemini Lite | 100 | 0.76 | 0.97 | 0.97 | 1.00 | 0.939 | 0.159 | 0.847 | 0.796 | 12,719 | $0.220 |
| Agentic H3 bounded + Gemini Lite | 100 | 0.55 | 0.73 | 0.74 | 0.75 | 0.679 | 0.282 | 0.607 | 0.562 | 15,055 | $0.870 |
| Agentic H3 bounded + Qwen3.5 4B | 100 | 0.65 | 0.79 | 0.81 | 0.85 | 0.777 | 0.145 | 0.701 | 0.654 | 44,570 | local |

The 100-case calibration is valid for direction, not final product gating. It already shows the pattern that remained true in the 1000-case attempt: the current agentic loop does not beat Pure H3.

## 1000-Case Saved Metrics

### Valid Quality Baseline Outside This Agentic Loop

The strongest valid saved 1000-case result is still the non-agentic H3 manifest answer-set run with Gemini 3.5 Flash:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | Cost | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest + Gemini 3.5 Flash | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.419 | 0.898 | 0.908 | 6542 | $34.94 | 0 |

Artifact:

```text
.code-diver/reports/intellij-h3-manifest-answer-sets-v2-gemini-flash-35-1000.json
```

This result passes `Hit@10 >= 0.95`, but Gemini 3.5 Flash should not be the routine model because this single run cost `$34.94`.

### Degraded Or Invalid Agentic 1000-Case Runs

| Setup | State | Completed | Failed | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | nDCG@10 | MAP@10 | Mean ms | Cost / usage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pure H3 + Gemini Lite | Degraded partial | 800 / 1000 | 0 recorded errors, but degraded | 0.789 | 0.909 | 0.944 | 0.971 | 0.952 | 0.279 | 0.866 | 0.832 | 13,584 | $0.924, 428 model calls |
| Agentic H3 bounded + Gemini Lite | Invalid, ADC reauth failures | 1000 / 1000 | 555 recorded errors | 0.290 | 0.341 | 0.355 | 0.361 | 0.347 | 0.121 | 0.313 | 0.297 | 6,846 | $3.869 before failure |
| Agentic H3 bounded + Qwen3.5 4B | Invalid, zero-byte artifact | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | local |

Pure H3 + Gemini Lite looks promising directionally, but it is not valid as a final quality metric because the partial artifact reports:

| Field | Value |
| --- | ---: |
| Completed cases | 800 / 1000 |
| `degraded` | `true` |
| `degraded_cases` | 372 |
| `rerank_errors` | 744 |
| `rerank_error_attempts` | 744 |
| `candidate_count_mean` | 30.0 |

The Gemini-agentic row is invalid. Its aggregate metrics count ADC failures as search misses after the API returned:

```text
Reauthentication is needed. Please run gcloud auth application-default login to reauthenticate.
```

That row can be used for operational cost/failure analysis, but not for search-quality comparison.

## Final Research Interpretation

The useful conclusions from this slice are:

- **Pure H3 is the baseline.** The valid Gemini 3.5 H3 run proves the architecture can pass `Hit@10 >= 0.95`; the Gemini Lite degraded partial suggests the cheaper reranker may be viable, but it needs a clean fail-fast rerun.
- **Agentic H3 is not the default path yet.** On the valid 100-case calibration it was worse than Pure H3, and the 1000-case Gemini run is invalid because of ADC failure.
- **Gemini 3.5 Flash should be retired from routine sweeps.** It is the best saved quality ceiling, but too expensive for iteration.
- **Gemini 3.1 Flash Lite remains useful.** It is the cheap API reranker/entrypoint to test first once the runner fails fast.
- **Qwen3.5 4B local is not ready for the agentic loop.** The saved 100-case bounded run reached Hit@10 `0.85`, but mean latency was `44,570 ms`.

## Operational Problems To Fix

1. **ADC reauth must abort the run.** Reauthentication failures should trip a fail-fast threshold instead of becoming hundreds of false search misses.
2. **Fail-soft degraded behavior must be visible and gated.** A run with `degraded_cases > 0` or rerank errors above a small threshold should be marked invalid for quality comparison.
3. **Partial artifacts need stage and validity fields.** Store `completed_cases`, `failed_cases`, `degraded_cases`, `rerank_errors`, and whether metrics exclude infrastructure failures.
4. **Agentic loops need budget caps.** Model/tool turns should have hard per-case limits and confidence-gated stopping.
5. **Full 1000-case API runs need a budget note.** Gemini 3.5 Flash is oracle-only unless explicitly approved for a small hard-case slice.
