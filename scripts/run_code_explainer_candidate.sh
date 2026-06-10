#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  cat >&2 <<'USAGE'
usage: scripts/run_code_explainer_candidate.sh <name> <config> [workers]

Example:
  scripts/run_code_explainer_candidate.sh qwen35-4b configs/explainers/qwen35-4b-local.yml 1

The script runs one isolated CodeXGLUE code-explanation candidate and judges
each generated explanation with the shared Vertex Gemini Flash-Lite judge.
USAGE
  exit 2
fi

NAME="$1"
CONFIG="$2"
WORKERS="${3:-1}"

DATASET=".code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl"
JUDGE_CONFIG="configs/explanation-judge-vertex-gemini31-flash-lite.yml"
JUDGE_PROMPT="prompts/code-explanation-judge.md"
OUTPUT=".code-diver/reports/code-explainer-${NAME}-vertex-gemini31-flash-lite-judge-100.json"
PARTIAL=".code-diver/reports/code-explainer-${NAME}-vertex-gemini31-flash-lite-judge-100.partial.json"

uv run code-diver --config "$CONFIG" \
  --help-all evaluate-explanations \
  --dataset "$DATASET" \
  --cases 100 \
  --yes \
  --judge \
  --judge-prompt "$JUDGE_PROMPT" \
  --judge-config "$JUDGE_CONFIG" \
  --workers "$WORKERS" \
  --output "$OUTPUT" \
  --partial-output "$PARTIAL"
