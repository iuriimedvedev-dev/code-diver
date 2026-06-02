#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

POLL_SECONDS="${POLL_SECONDS:-300}"
RUN_DIR=".code-diver/reports/overnight-h2"
SUMMARY_MD="docs/intellij-h2-matrix-overnight-2026-06-02.md"
SUMMARY_JSON=".code-diver/reports/intellij-h2-matrix-overnight-summary.json"

ts() {
  python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))'
}

summarize() {
  uv run python scripts/summarize_h2_matrix.py \
    --output "$SUMMARY_MD" \
    --json-output "$SUMMARY_JSON" \
    >/tmp/code-diver-h2-watch-summary.log 2>&1 || true
}

print_status() {
  echo "[$(ts)] h2 watch tick"
  if [[ -f "$RUN_DIR/status.log" ]]; then
    tail -8 "$RUN_DIR/status.log"
  fi
  for label in qwen35_4b gemini_flash_lite gemini_flash_35 h3-gemini-flash-lite h3-gemini-flash-35 h4-gemini-flash-lite h4-gemini-flash-35; do
    local log="$RUN_DIR/$label.log"
    if [[ -f "$log" ]]; then
      local last_progress
      last_progress="$(grep -E 'case [0-9]+/1000|Traceback|ERROR|Error' "$log" | tail -3 || true)"
      echo "--- $label ---"
      if [[ -n "$last_progress" ]]; then
        echo "$last_progress"
      else
        tail -3 "$log" || true
      fi
    fi
  done
  if [[ -f "$SUMMARY_MD" ]]; then
    echo "--- summary ---"
    sed -n '1,28p' "$SUMMARY_MD"
  fi
}

summarize
print_status

while pgrep -f "scripts/run_postrank_h2_deterministic.py" >/dev/null; do
  sleep "$POLL_SECONDS"
  summarize
  print_status
done

summarize
print_status
echo "[$(ts)] h2 watch completed"
