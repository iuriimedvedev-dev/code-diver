#!/usr/bin/env bash
# Serve the Qwen3 embedding model on :8001.
#
# This is the one server EVERY axis needs -- search, answers, explanations. Its command line
# lived only in the shell history of whoever started it, which meant stopping it risked losing
# the ability to restart it. Hence this file.
#
# --max-model-len 512 matches how the index was BUILT. Changing it silently changes what the
# embeddings mean, and every collection in Qdrant would have to be rebuilt to match. The
# collection names encode the model and chunk size (e.g. ..._qwen3_embedding_0_6b_4bit_dwq_
# autod_400c_...), so a mismatch here does not fail loudly -- it just retrieves worse.
#
# --runner pooling is required: without it vllm serves a generative endpoint and the embedding
# calls fail.
#
# vllm lives in .venv-vllm-metal-official, NOT the project venv, and its wheel is fetched from
# GitHub. Never reinstall or `uv run` this: a network blip has already killed eval arms.
set -euo pipefail

VENV="${EMBEDDER_VENV:-.venv-vllm-metal-official}"
MODEL="${EMBEDDER_MODEL:-mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ}"
PORT="${EMBEDDER_PORT:-8001}"
MAX_LEN="${EMBEDDER_MAX_MODEL_LEN:-512}"
LOG="${EMBEDDER_LOG:-/private/tmp/vllm-embedder-${PORT}.log}"

# Pin the rendezvous address to loopback. vllm otherwise picks the first non-loopback address,
# which on this machine is the Cloudflare WARP interface (100.96.5.x, reverse-resolving to
# connectivity-check.warp-svc). The gloo store then tries to bind/connect there and hangs
# forever in `parallel_state` -- the server never reaches the point of listening on the port,
# so the failure looks like "the embedder just never came up". One worker, all on loopback.
export VLLM_HOST_IP="${VLLM_HOST_IP:-127.0.0.1}"
export GLOO_SOCKET_IFNAME="${GLOO_SOCKET_IFNAME:-lo0}"
export VLLM_METAL_MEMORY_FRACTION="${VLLM_METAL_MEMORY_FRACTION:-0.3}"

if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port ${PORT} is already in use -- stop the existing server first" >&2
  exit 1
fi

exec "${VENV}/bin/python" "${VENV}/bin/vllm" serve "${MODEL}" \
  --runner pooling \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --max-model-len "${MAX_LEN}" \
  >>"${LOG}" 2>&1
