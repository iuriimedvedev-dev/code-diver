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
#
# 768 is measured, not guessed. Sweep over 47 fixed payloads (25 IntelliJ + 22
# CodeSearchNet, including the 8 that failed at 512), pools precomputed so only the
# reranker was timed:
#
#   ubatch   IntelliJ    CSN     failures
#      512    1754 ms   1973 ms   7/22 on CSN
#      768    1645 ms   2216 ms   0        <- smallest with no failures, and fastest
#     1024    1819 ms   2523 ms   0
#     2048    2173 ms   2731 ms   0
#     4096    2203 ms   2694 ms   0
#
# Bigger is not safer, it is just slower: 4096 costs ~25% over 768 on IntelliJ and
# buys nothing, since 768 already clears the longest pair (max prompt 21 850 tokens
# across 34 documents). Raise it only if max_document_chars or query length grows.
set -euo pipefail

MODEL="${RERANKER_MODEL:-.code-diver/models/rerankers/qwen3-reranker-0.6b/Qwen3-Reranker-0.6B-Q4_K_M.gguf}"
PORT="${RERANKER_PORT:-8081}"
BATCH="${RERANKER_BATCH:-768}"
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
