#!/usr/bin/env bash
# Serve the Qwen3 cross-encoder reranker on :8081.
#
# The batch sizes are not optional. With --embedding, llama-server clamps
# n_batch = n_ubatch and defaults to 512:
#
#   llama_server: embeddings enabled with n_batch (2048) > n_ubatch (512)
#   llama_server: setting n_batch = n_ubatch = 512 to avoid assertion failure
#
# Non-causal pooling needs the whole sequence in one physical batch, so any
# query+document pair longer than n_ubatch fails the ENTIRE /rerank request:
#
#   error: input (564 tokens) is too large to process.
#          increase the physical batch size (current batch size: 512)
#
# CrossEncoderRerankRetrievalStrategy catches that and returns base order, so the
# damage is silent -- 22% of CodeSearchNet cases were never reranked before this
# was found. Keep -b and -ub at or above the largest query+document pair you send
# (max_document_chars 850 ~= 250 tokens, plus the query).
set -euo pipefail

MODEL="${RERANKER_MODEL:-.code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf}"
PORT="${RERANKER_PORT:-8081}"
BATCH="${RERANKER_BATCH:-4096}"
LOG="${RERANKER_LOG:-/private/tmp/llama-server-${PORT}.log}"

if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port ${PORT} is already in use -- stop the existing server first" >&2
  exit 1
fi

exec llama-server \
  --model "${MODEL}" \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --embedding \
  --reranking \
  --pooling rank \
  --batch-size "${BATCH}" \
  --ubatch-size "${BATCH}" \
  >>"${LOG}" 2>&1
