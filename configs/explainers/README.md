# Code Explainer Candidate Configs

These configs are for isolated `evaluate-explanations` runs on the same
CodeXGLUE code-to-text Python dataset. They are explainer configs, not judge
configs and not end-to-end answer/retrieval configs.

Default command shape:

```bash
uv run code-diver --config configs/explainers/<candidate>.yml \
  --help-all evaluate-explanations \
  --cases 100 \
  --yes \
  --judge \
  --judge-prompt prompts/code-explanation-judge.md \
  --judge-config configs/explanation-judge-vertex-gemini31-flash-lite.yml \
  --workers <workers> \
  --output .code-diver/reports/code-explainer-<candidate>-vertex-gemini31-flash-lite-judge-100.json \
  --partial-output .code-diver/reports/code-explainer-<candidate>-vertex-gemini31-flash-lite-judge-100.partial.json
```

Local runtime expectations:

| Config | Expected server |
| --- | --- |
| `gemma4-e2b-local.yml` | OpenAI-compatible local server on `127.0.0.1:8012` |
| `gemma4-e4b-local.yml` | OpenAI-compatible local server on `127.0.0.1:8013` |
| `gemma4-12b-local.yml` | OpenAI-compatible local server on `127.0.0.1:8015` |
| `gemma4-26b-local.yml` | llama.cpp OpenAI-compatible server on `127.0.0.1:8016` |
| `qwen35-4b-local.yml` | MLX OpenAI-compatible server on `127.0.0.1:8012` |
| `qwen35-9b-local.yml` | MLX OpenAI-compatible server on `127.0.0.1:8014` |
| `vertex-gemini31-flash-lite.yml` | Vertex ADC auth, no local server |

Suggested local server commands for Qwen/Gemma MLX candidates, from the repo
root:

```bash
.venv-vllm-metal-official/bin/mlx_lm.server \
  --model mlx-community/Qwen3.5-4B-OptiQ-4bit \
  --host 127.0.0.1 \
  --port 8012 \
  --max-tokens 2048 \
  --temp 0 \
  --prompt-concurrency 1 \
  --decode-concurrency 1 \
  --chat-template-args '{"enable_thinking": false}'

.venv-vllm-metal-official/bin/mlx_lm.server \
  --model mlx-community/Qwen3.5-9B-MLX-4bit \
  --host 127.0.0.1 \
  --port 8014 \
  --max-tokens 2048 \
  --temp 0 \
  --prompt-concurrency 1 \
  --decode-concurrency 1 \
  --chat-template-args '{"enable_thinking": false}'

.venv-vllm-metal-official/bin/mlx_lm.server \
  --model .code-diver/models/mlx-community-gemma-4-12B-it-4bit \
  --host 127.0.0.1 \
  --port 8015 \
  --max-tokens 2048 \
  --temp 0 \
  --prompt-concurrency 1 \
  --decode-concurrency 1
```

Only run one model per port. If `8012` is used by Qwen 4B, do not also expect
Gemma E2B there until the server is switched.

Run a candidate with the shared wrapper:

```bash
scripts/run_code_explainer_candidate.sh qwen35-4b configs/explainers/qwen35-4b-local.yml 1
scripts/run_code_explainer_candidate.sh qwen35-9b configs/explainers/qwen35-9b-local.yml 1
scripts/run_code_explainer_candidate.sh gemma4-12b configs/explainers/gemma4-12b-local.yml 1
scripts/run_code_explainer_candidate.sh gemma4-26b configs/explainers/gemma4-26b-local.yml 1
scripts/run_code_explainer_candidate.sh gemini31-flash-lite configs/explainers/vertex-gemini31-flash-lite.yml 8
```

Summarize completed per-answer judge reports:

```bash
uv run python scripts/summarize_explainer_matrix.py --markdown \
  .code-diver/reports/code-explainer-*-vertex-gemini31-flash-lite-judge-100.json
```

Run the blind listwise meta-judge only after all candidate reports are complete:

```bash
uv run python scripts/meta_judge_explainer_candidates.py \
  --dataset .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl \
  --judge-config configs/explanation-judge-vertex-gemini31-flash-lite.yml \
  --candidate gemma-e4b=.code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json \
  --candidate gemini31-flash-lite=.code-diver/reports/code-explainer-gemini31-flash-lite-vertex-gemini31-flash-lite-judge-100.json \
  --candidate gemma26=.code-diver/reports/code-explainer-gemma26-vertex-gemini31-flash-lite-judge-100.json \
  --cases 100 \
  --workers 8 \
  --seed 17 \
  --output .code-diver/reports/code-explainer-meta-judge-vertex-gemini31-flash-lite-100.json \
  --partial-output .code-diver/reports/code-explainer-meta-judge-vertex-gemini31-flash-lite-100.partial.json \
  --markdown
```

The meta-judge sends one request per CodeXGLUE case. Each request contains the
code, metadata, reference answer, and the candidate explanations in balanced
random slot order; it saves the slot-to-candidate permutation for position-bias
auditing.
