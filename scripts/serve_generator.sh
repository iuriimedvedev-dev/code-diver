#!/usr/bin/env bash
# Serve the Qwen3.5-4B generator on :8012.
#
# Answer-axis and explanation-axis runs need this; search-axis evaluate runs do not.
# Stop it before a timed retrieval arm -- see scripts/serve_judge.sh for why.
#
# mlx_lm lives in the vllm-metal venv, not the project venv. Call its entry point
# directly: `uv run` re-resolves dependencies on every invocation and reaches GitHub
# for the vllm-metal wheel, which has already killed runs on a network blip.
set -euo pipefail

VENV="${GENERATOR_VENV:-.venv-vllm-metal-official}"
MODEL="${GENERATOR_MODEL:-mlx-community/Qwen3.5-4B-OptiQ-4bit}"
PORT="${GENERATOR_PORT:-8012}"
LOG="${GENERATOR_LOG:-/private/tmp/mlx-server-${PORT}.log}"

if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port ${PORT} is already in use -- stop the existing server first" >&2
  exit 1
fi

exec "${VENV}/bin/python" "${VENV}/bin/mlx_lm" server \
  --model "${MODEL}" \
  --host 127.0.0.1 \
  --port "${PORT}" \
  >>"${LOG}" 2>&1
