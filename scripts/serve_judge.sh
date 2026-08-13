#!/usr/bin/env bash
# Serve the gemma-4-12B judge on :8030.
#
# The judge is only needed for answer-axis and explanation-axis runs. Search-axis
# evaluate runs do NOT touch it, and a 12B model left resident costs ~8 GB that the
# machine then has to compress or swap. Latency is a measured quantity (Finding 37),
# so stop this before a timed retrieval arm and start it again for judging.
#
# --ctx-size 32768 is required: the rubric prompt plus the cited file windows
# routinely exceeds the 4096 default, and llama-server truncates silently.
set -euo pipefail

MODEL="${JUDGE_MODEL:-.code-diver/models/gemma-4-12b-it-qat-GGUF/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf}"
ALIAS="${JUDGE_ALIAS:-gemma-4-12B-it-qat-UD-Q4_K_XL}"
PORT="${JUDGE_PORT:-8030}"
CTX="${JUDGE_CTX:-32768}"
LOG="${JUDGE_LOG:-/private/tmp/llama-server-${PORT}.log}"

if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port ${PORT} is already in use -- stop the existing server first" >&2
  exit 1
fi

exec llama-server \
  --model "${MODEL}" \
  --alias "${ALIAS}" \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --ctx-size "${CTX}" \
  --jinja \
  >>"${LOG}" 2>&1
