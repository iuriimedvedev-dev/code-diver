#!/usr/bin/env bash
# Serve the MLX Qwen3 cross-encoder reranker via the vLLM-metal pooling server.
#
# Why this exists: the in-process MLX scorer lost to llama.cpp (23s vs 2s per
# 34-doc batch, docs/research/2026-09-08_mlx-benchmark.md), but the vLLM-metal
# pooling server scored a 34-long batch in 1.3s
# (docs/research/2026-09-09_mlx-search-recovery.md) -- while strangled by
# --max-num-seqs 1. This script relaunches the same server with throughput
# tuning so up to 34 documents batch together instead of serializing.
#
# Key differences vs the recovery probe (see README section below for details):
#   recovery:  --max-num-seqs 1 --max-num-batched-tokens 2048 --max-model-len 2048
#   this:      --max-num-seqs 32 --max-num-batched-tokens 16384 --max-model-len 4096
#
# The server exposes POST /rerank (NOT /v1/rerank -- that route 404s; the Rust
# CE client handles both with --ce-route auto). Point the Rust client at it:
#   code-diver-search ... --ce-url http://127.0.0.1:18083/rerank
#
# This script only DEFINES the launch; it never starts anything on import and
# must be run explicitly. First start downloads the pinned snapshot unless
# HF_HUB_CACHE already holds it (no download happens by merely reading this file).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- tunables (all overridable via env) --------------------------------------
MLX_CE_PORT="${MLX_CE_PORT:-18083}"
MLX_CE_HOST="${MLX_CE_HOST:-127.0.0.1}"
MLX_CE_VENV="${MLX_CE_VENV:-$REPO_ROOT/.venv-vllm-metal-official}"
MLX_CE_MODEL="${MLX_CE_MODEL:-mlx-community/Qwen3-Reranker-0.6B-4bit}"
# Pinned snapshot from the 2026-09-09 recovery run; --revision keeps it fixed.
MLX_CE_REVISION="${MLX_CE_REVISION:-5f324548f1d20c2b5a450f126fc6ef2fb1126524}"
# Throughput tuning: a 34-doc batch must fit in one scheduling step.
MLX_CE_MAX_SEQS="${MLX_CE_MAX_SEQS:-32}"
MLX_CE_BATCHED_TOKENS="${MLX_CE_BATCHED_TOKENS:-16384}"
MLX_CE_MAX_MODEL_LEN="${MLX_CE_MAX_MODEL_LEN:-4096}"
MLX_CE_BLOCK_SIZE="${MLX_CE_BLOCK_SIZE:-16}"
MLX_CE_GPU_UTIL="${MLX_CE_GPU_UTIL:-0.35}"
MLX_CE_MEM_FRACTION="${MLX_CE_MEM_FRACTION:-0.35}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$REPO_ROOT/.tmp/mlx-model-cache/huggingface}"
MLX_CE_LOG="${MLX_CE_LOG:-/private/tmp/vllm-metal-ce-${MLX_CE_PORT}.log}"
# Official Qwen3 reranker chat template extracted from the snapshot
# (tokenizer_config.json -> chat_template). If unset/missing, vLLM falls back
# to the tokenizer's built-in template with a warning (see README).
MLX_CE_CHAT_TEMPLATE="${MLX_CE_CHAT_TEMPLATE:-$REPO_ROOT/.tmp/qwen3-reranker-official-chat-template.jinja}"

if [[ ! -x "$MLX_CE_VENV/bin/vllm" ]]; then
  echo "vllm not found at $MLX_CE_VENV/bin/vllm (override with MLX_CE_VENV)" >&2
  exit 1
fi

if lsof -nP -iTCP:"${MLX_CE_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port ${MLX_CE_PORT} is already in use -- stop the existing server first" >&2
  exit 1
fi

CHAT_TEMPLATE_ARGS=()
if [[ -f "$MLX_CE_CHAT_TEMPLATE" ]]; then
  CHAT_TEMPLATE_ARGS=(--chat-template "$MLX_CE_CHAT_TEMPLATE")
else
  echo "WARNING: official chat template not found at $MLX_CE_CHAT_TEMPLATE;" >&2
  echo "  continuing with the tokenizer built-in template (override with MLX_CE_CHAT_TEMPLATE)." >&2
fi

export VLLM_ENABLE_V1_MULTIPROCESSING=0
export VLLM_METAL_USE_PAGED_ATTENTION=1
export VLLM_METAL_MEMORY_FRACTION="$MLX_CE_MEM_FRACTION"

echo "serving $MLX_CE_MODEL@$MLX_CE_REVISION on $MLX_CE_HOST:$MLX_CE_PORT (log: $MLX_CE_LOG)" >&2
exec "$MLX_CE_VENV/bin/vllm" serve "$MLX_CE_MODEL" \
  --revision "$MLX_CE_REVISION" \
  --host "$MLX_CE_HOST" \
  --port "$MLX_CE_PORT" \
  --runner pooling \
  --max-model-len "$MLX_CE_MAX_MODEL_LEN" \
  --gpu-memory-utilization "$MLX_CE_GPU_UTIL" \
  --block-size "$MLX_CE_BLOCK_SIZE" \
  --max-num-seqs "$MLX_CE_MAX_SEQS" \
  --max-num-batched-tokens "$MLX_CE_BATCHED_TOKENS" \
  "${CHAT_TEMPLATE_ARGS[@]}" \
  --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}' \
  >>"$MLX_CE_LOG" 2>&1
