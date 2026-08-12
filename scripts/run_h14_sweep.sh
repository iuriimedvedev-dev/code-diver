#!/usr/bin/env bash
# Runs the H14 text-graph evaluation across every local generation model, one at a time.
#
# Serial by design: each model holds 3-8 GB of unified memory, and two MLX servers competing
# for it would make the latency numbers meaningless. A failing model does not stop the sweep
# -- a model that cannot complete the task is itself a result, and stopping would forfeit the
# models after it in the list.
set -uo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
JUDGE_LABEL="${JUDGE_LABEL:-qwen35-9b}"
# Written the long way: on bash 3.2 (what /usr/bin/env bash resolves to on macOS)
# `LABELS=("${@}")` with no arguments trips `set -u` before the default can be applied.
if [ $# -gt 0 ]; then
  LABELS=("$@")
else
  # qwen35-4b first: it is the promoted model from the sweep results.
  LABELS=(qwen35-4b qwen35-9b gemma4-e2b gemma4-e4b)
fi

LOG_DIR="/tmp/h14-sweep"
mkdir -p "$LOG_DIR"
FAILED=""

for label in "${LABELS[@]}"; do
  echo ""
  echo "############ $label ############"
  if ! "$DIR/scripts/run_h14_model.sh" "$label" "$JUDGE_LABEL" 2>&1 | tee "$LOG_DIR/${label}.log"; then
    FAILED="$FAILED $label"
    echo "!!! $label failed -- see $LOG_DIR/${label}.log"
  fi
done

echo ""
echo "############ sweep summary ############"
# These two paths must match what run_h14_model.sh itself writes to (BUDGET_SUFFIX and the
# JUDGE_OUT derivation), or this summary silently points at the wrong -- or a nonexistent --
# file. The judge path is derived through scripts/judge_report_naming.py, the same helper
# run_h14_model.sh uses, rather than re-hand-built here, for exactly that reason.
BUDGET_SUFFIX=""
if [ "${CONTEXT_FILES:-4}" != "4" ] || [ "${CONTEXT_LINES:-160}" != "160" ]; then
  BUDGET_SUFFIX="-cf${CONTEXT_FILES:-4}-cl${CONTEXT_LINES:-160}"
fi
for label in "${LABELS[@]}"; do
  report="$DIR/.code-diver/reports/protogen-h14-${label}-text-graph-${CASES:-100}${BUDGET_SUFFIX}.json"
  judge="$(uv run --project "$DIR" python "$DIR/scripts/judge_report_naming.py" "$report" --judge-label "$JUDGE_LABEL")"
  uv run --project "$DIR" python "$DIR/scripts/summarize_h14_run.py" "$report" --judge-report "$judge" --label "$label"
done

if [ -n "$FAILED" ]; then
  echo ""
  echo "failed:$FAILED"
  exit 1
fi
