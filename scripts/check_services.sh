#!/usr/bin/env bash
# Quickstart launcher for code-diver model backend services
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== code-diver service launcher ==="

# Check Qdrant
echo -n "1. Checking Qdrant on :6333... "
if curl -s http://127.0.0.1:6333/collections >/dev/null 2>&1; then
    echo "RUNNING"
else
    echo "NOT RUNNING"
    echo "   Start via docker: docker run -d -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant"
fi

# Check Embedding
echo -n "2. Checking Embedding model on :8001... "
if curl -s http://127.0.0.1:8001/v1/models >/dev/null 2>&1; then
    echo "RUNNING"
else
    echo "NOT RUNNING"
    echo "   Recommended: vllm serve mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ --runner pooling --host 127.0.0.1 --port 8001 --max-model-len 512"
fi

# Check CE Reranker
echo -n "3. Checking CE Reranker on :18081... "
if curl -s http://127.0.0.1:18081/health >/dev/null 2>&1; then
    echo "RUNNING"
else
    echo "NOT RUNNING"
    echo "   Recommended: llama-server -m Qwen3-Reranker-0.6B-Q4_K_M.gguf --host 127.0.0.1 --port 18081 --ctx-size 40960 --batch-size 2048 --ubatch-size 2048 --pooling rank --reranking"
fi

echo "==================================="
echo "Run doctor self-check:"
echo "  ${DIST_DIR}/bin/code-diver --doctor"
