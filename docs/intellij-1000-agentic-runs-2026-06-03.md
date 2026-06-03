# IntelliJ 1000-Case Runs - 2026-06-03

This report tracks the current 1000-case IntelliJ answer-set runs.

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

## Active 1000-Case Jobs

| Screen | Setup | Output | Notes |
| --- | --- | --- | --- |
| `cdv-1000-pure-h3-gemini-lite` | Pure H3 deterministic branch C + Gemini 3.1 Flash Lite rerank | `.code-diver/reports/agentic-h3-1000/intellij-1000-pure-h3-gemini-lite.json` | Trusted baseline. Restarted with `--cases 1000`; an earlier attempt accidentally used the script default 100 cases and was discarded. |
| `cdv-1000-agentic-gemini-lite` | Agentic H3 bounded tools + Gemini 3.1 Flash Lite | `.code-diver/reports/agentic-h3-1000/intellij-1000-agentic-h3-gemini-lite-bounded.json` | Tests whether LLM query/tool planning helps once probes are runtime-bounded. |
| `cdv-1000-agentic-qwen35` | Agentic H3 bounded tools + local Qwen3.5 4B OptiQ 4bit | `.code-diver/reports/agentic-h3-1000/intellij-1000-agentic-h3-qwen35-bounded.json` | Local quality hypothesis; expected to be much slower. |

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

The expected result is that Pure H3 remains the baseline. The useful research question is whether either agentic setup closes the gap on the full 1000-case distribution.

## Current Interpretation Before 1000 Completes

Bounded tools fixed the main tool-layer latency bugs:

- broad `grep`/`rg` calls are scoped to candidate files;
- mixed parallel batches stage first-pass H3/search before unscoped probes;
- broad `symbols(path="java")` style calls are intersected with candidate files.

The remaining bottleneck is model policy: the agent still makes many model/rerank turns, and quality depends on whether fast H3 candidate generation contains the right files before rerank.
