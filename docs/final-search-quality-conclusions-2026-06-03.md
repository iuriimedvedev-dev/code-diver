# Final Search Quality Conclusions - 2026-06-03

This is the final research slice for the current IntelliJ 1000-case search-quality work. It consolidates the saved metrics and marks invalid/degraded runs explicitly.

## Bottom Line

The target `Hit@10 >= 0.95` is reachable with the current non-agentic H3 architecture.

The best valid saved full run is:

| Setup | Dataset | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | Cost | Degraded |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest + Gemini 3.5 Flash | `datasets/intellij_eval_1000.answer_sets.jsonl` | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.419 | 0.898 | 0.908 | 6542 | $34.94 | 0 |

Artifact:

```text
.code-diver/reports/intellij-h3-manifest-answer-sets-v2-gemini-flash-35-1000.json
```

This is a quality ceiling, not the recommended routine workflow. Gemini 3.5 Flash is too expensive for repeated full sweeps.

## Valid Metrics

These are safe to use for conclusions:

| Run | Cases | Status | Main Conclusion |
| --- | ---: | --- | --- |
| H3 manifest + Gemini 3.5 Flash answer-set v2 | 1000 | Valid, no degraded cases | Current quality ceiling; passes Hit@10 target. |
| H2 answer-set six-way completed rows | 1000 each | Valid, no degraded cases in saved rows | Historical comparison: Branch A/B are weaker than H3 and should not drive architecture now. |
| Agentic H3 100-case calibration | 100 each | Valid small-sample comparison | Agentic H3 was worse/slower/more expensive than Pure H3 on the saved 100-case slice. |

Useful saved comparison points:

| Setup | Cases | Hit@1 | Hit@10 | nDCG@10 | Mean ms | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pure H3 + Gemini Lite rerank | 100 | 0.76 | 1.00 | 0.847 | 12,719 | $0.220 |
| Agentic H3 + Gemini Lite | 100 | 0.56 | 0.80 | 0.654 | 14,630 | $0.866 |
| Agentic H3 bounded + Gemini Lite | 100 | 0.55 | 0.75 | 0.607 | 15,055 | $0.870 |
| Agentic H3 bounded + Qwen3.5 4B local | 100 | 0.65 | 0.85 | 0.701 | 44,570 | local |

## Invalid Or Degraded Metrics

Do not use these for search-quality selection:

| Run | Saved State | Why Invalid/Degraded |
| --- | --- | --- |
| Pure H3 + Gemini Lite 1000-case partial | 800 / 1000, `degraded=true`, `degraded_cases=372`, `rerank_errors=744` | Directional only. Fail-soft fallback mixed into metrics. |
| Agentic H3 bounded + Gemini Lite 1000-case | 1000 cases, `error_count=555` | ADC reauthentication failures were counted as misses. |
| Agentic H3 bounded + Qwen3.5 4B 1000-case | zero-byte JSON artifact | No usable metrics. |

The ADC failure text in the invalid Gemini-agentic run was:

```text
Reauthentication is needed. Please run gcloud auth application-default login to reauthenticate.
```

## Model Conclusions

| Model | Current Role | Reason |
| --- | --- | --- |
| Gemini 3.5 Flash | Oracle / quality ceiling only | Best saved quality, but full 1000-case H3 run cost `$34.94`. |
| Gemini 3.1 Flash Lite | Cheap API reranker/entrypoint | Much cheaper; good candidate for clean reruns once fail-fast is fixed. |
| Qwen3.5 4B local | Local candidate, not default agent | Valid 100-case bounded run reached Hit@10 `0.85`, but mean latency was `44,570 ms`. |

## Architecture Conclusions

1. **Pure H3 is the production baseline.** It already reaches target quality with the expensive oracle reranker.
2. **Agentic H3 is research-only for now.** The current loop spends more calls and does not beat deterministic H3.
3. **Use LLMs surgically.** The strongest use is cheap reranking/entrypoint planning over strong deterministic candidates, not open-ended multi-turn exploration for every case.
4. **Do not optimize against degraded runs.** The runner must fail fast when auth/model failures exceed a threshold.
5. **Next useful experiment:** clean H3 manifest + Gemini 3.1 Flash Lite full answer-set run after fail-fast/degraded gating is implemented.

## Required Runner Fixes Before More Full Sweeps

- Abort on ADC/auth failures instead of recording them as search misses.
- Add a degraded threshold, for example fail the run when `degraded_cases > 0` for quality gates or when rerank errors exceed a tiny configured limit.
- Emit explicit validity status in every report: `valid`, `degraded_partial`, or `invalid`.
- Store metrics with and without infrastructure failures if recovery is needed for operational analysis.
- Keep full 1000-case API runs behind an explicit budget note.
