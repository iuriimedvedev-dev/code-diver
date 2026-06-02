#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_DIR=".code-diver/reports/overnight-h2"
mkdir -p "$RUN_DIR"
mkdir -p ".code-diver/reports/partials-qwen-1000"
mkdir -p ".code-diver/reports/partials-gemini-flash-lite-1000"
mkdir -p ".code-diver/reports/partials-gemini-flash-35-1000"

ts() {
  python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'
}

echo "[$(ts)] overnight H2 matrix started" | tee "$RUN_DIR/status.log"

curl -sS --max-time 5 http://127.0.0.1:6333/healthz | tee "$RUN_DIR/qdrant-health.log"
curl -sS --max-time 5 http://127.0.0.1:8001/v1/models > "$RUN_DIR/embedding-models.json"
curl -sS --max-time 5 http://127.0.0.1:8012/v1/models > "$RUN_DIR/local-generation-models.json"

run_eval() {
  local label="$1"
  local partial_dir="$2"
  local output="$3"
  local report="$4"
  shift 4
  echo "[$(ts)] starting $label" | tee -a "$RUN_DIR/status.log"
  uv run python scripts/run_postrank_h2_deterministic.py \
    --cases 1000 \
    --progress-every 25 \
    --partial-dir "$partial_dir" \
    --output "$output" \
    --report "$report" \
    "$@" \
    > "$RUN_DIR/$label.log" 2>&1
  echo "[$(ts)] finished $label status=$?" | tee -a "$RUN_DIR/status.log"
}

run_eval qwen35_4b \
  .code-diver/reports/partials-qwen-1000 \
  .code-diver/reports/intellij-postrank-h2-deterministic-qwen-1000.json \
  .code-diver/reports/intellij-postrank-h2-deterministic-qwen-1000.html \
  --hypothesis h2a_grep_read_rerank_qwen35_4b \
  --hypothesis h2b_ephemeral_rerank_qwen35_4b &
PID_QWEN=$!

run_eval gemini_flash_lite \
  .code-diver/reports/partials-gemini-flash-lite-1000 \
  .code-diver/reports/intellij-postrank-h2-deterministic-gemini-flash-lite-1000.json \
  .code-diver/reports/intellij-postrank-h2-deterministic-gemini-flash-lite-1000.html \
  --hypothesis h2a_grep_read_rerank_gemini_flash_lite \
  --hypothesis h2b_ephemeral_rerank_gemini_flash_lite &
PID_LITE=$!

run_eval gemini_flash_35 \
  .code-diver/reports/partials-gemini-flash-35-1000 \
  .code-diver/reports/intellij-postrank-h2-deterministic-gemini-flash-35-1000.json \
  .code-diver/reports/intellij-postrank-h2-deterministic-gemini-flash-35-1000.html \
  --hypothesis h2a_grep_read_rerank_gemini_flash_35 \
  --hypothesis h2b_ephemeral_rerank_gemini_flash_35 &
PID_FLASH=$!

set +e
wait "$PID_QWEN"; QWEN_STATUS=$?
wait "$PID_LITE"; LITE_STATUS=$?
wait "$PID_FLASH"; FLASH_STATUS=$?
set -e

{
  echo "qwen35_4b=$QWEN_STATUS"
  echo "gemini_flash_lite=$LITE_STATUS"
  echo "gemini_flash_35=$FLASH_STATUS"
} > "$RUN_DIR/eval-status.env"

uv run python scripts/summarize_h2_matrix.py \
  --output docs/intellij-h2-matrix-overnight-2026-06-02.md \
  --json-output .code-diver/reports/intellij-h2-matrix-overnight-summary.json \
  > "$RUN_DIR/summarize.log" 2>&1

cat > "$RUN_DIR/brainstorm-prompt.md" <<'PROMPT'
We are building code-diver, a repository-agnostic code search/RAG benchmark.

Current architecture:
- persistent first-stage file locator index over IntelliJ: one file_summary vector per file, local Qwen3-Embedding-0.6B 4bit, Qdrant;
- Branch A: locator -> outline/symbol/rg probes -> listwise LLM rerank;
- Branch B: locator -> ephemeral syntax-aware vector index over candidate files -> listwise LLM rerank;
- rankers under comparison: local Qwen3.5 4B, Vertex Gemini 3.1 Flash-Lite, Vertex Gemini 3.5 Flash.

Artifacts to inspect:
- docs/intellij-h2-matrix-overnight-2026-06-02.md
- .code-diver/reports/intellij-h2-matrix-overnight-summary.json
- docs/Explanation.md
- docs/intellij-file-locator-sweep-2026-06-02.md
- docs/intellij-postrank-h2-2026-06-02.md

Task:
1. Explain which tool/indexing branch is strongest and why.
2. Find failure patterns and likely ranking/indexing bottlenecks.
3. Propose concrete next experiments that could improve Hit@1 without blowing up index size past 1-3GB.
4. Focus on hybrid indexes, multi-index candidate generation, route-specific search, and better reranking.
5. Be specific: name metrics to track and acceptance criteria.
PROMPT

if command -v claude >/dev/null 2>&1; then
  claude -p --model claude-opus-4-8 --effort high \
    "$(cat "$RUN_DIR/brainstorm-prompt.md")" \
    > "$RUN_DIR/claude-opus-brainstorm.md" 2> "$RUN_DIR/claude-opus-brainstorm.err" || true
fi

if command -v gemini >/dev/null 2>&1; then
  for model in gemini-3-pro gemini-2.5-pro; do
    if gemini -m "$model" -p "$(cat "$RUN_DIR/brainstorm-prompt.md")" \
      > "$RUN_DIR/gemini-pro-brainstorm.md" 2> "$RUN_DIR/gemini-pro-brainstorm.err"; then
      echo "$model" > "$RUN_DIR/gemini-pro-model.txt"
      break
    fi
  done
fi

uv run python scripts/summarize_h2_matrix.py \
  --output docs/intellij-h2-matrix-overnight-2026-06-02.md \
  --json-output .code-diver/reports/intellij-h2-matrix-overnight-summary.json \
  >> "$RUN_DIR/summarize.log" 2>&1

echo "[$(ts)] overnight H2 matrix completed" | tee -a "$RUN_DIR/status.log"
