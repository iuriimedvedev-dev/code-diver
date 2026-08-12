#!/usr/bin/env bash
set -euo pipefail

MODEL_LABEL="$1"
DIR="$(cd "$(dirname "$0")/.." && pwd)"

case "$MODEL_LABEL" in
  gemma4-12b) PORT=8022; GGUF="/tmp/gguf-models/gemma4-12b/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf" ;;
  gemma4-e2b)  PORT=8023; GGUF="/tmp/gguf-models/gemma4-e2b/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf" ;;
  gemma4-e4b)  PORT=8024; GGUF="/tmp/gguf-models/gemma4-e4b/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf" ;;
  *)
    echo "Unknown: $MODEL_LABEL"
    exit 1
    ;;
esac

CFG="$DIR/configs/context-awareness/protogen-h14-${MODEL_LABEL}-text-graph.yml"
OUT="$DIR/.code-diver/reports/protogen-h14-${MODEL_LABEL}-text-graph-100.json"
PARTIAL="$DIR/.code-diver/reports/protogen-h14-${MODEL_LABEL}-text-graph-100.partial.json"
JUDGE_LABEL="qwen35-9b"
# The judged-report path is derived FROM $OUT (not hand-built from separate variables) so it
# always carries every distinguishing suffix $OUT has -- see scripts/judge_report_naming.py
# for why: a hand-built path here (as this script used to do, unconditionally, with no
# case-count suffix at all) is exactly what let any two runs of the same model collide.
JUDGE_OUT="$(uv run --project "$DIR" python "$DIR/scripts/judge_report_naming.py" "$OUT" --judge-label "$JUDGE_LABEL")"
JUDGE_PARTIAL="$(uv run --project "$DIR" python "$DIR/scripts/judge_report_naming.py" "$OUT" --judge-label "$JUDGE_LABEL" --partial)"
mkdir -p "$(dirname "$OUT")" "$(dirname "$JUDGE_OUT")"

# Refuse to silently clobber an existing report (or its .partial.json recovery sibling)
# from a prior run of this model.
ALLOW_OVERWRITE="${ALLOW_OVERWRITE:-}"
if [ -z "$ALLOW_OVERWRITE" ]; then
  for guard_path in "$OUT" "$PARTIAL" "$JUDGE_OUT" "$JUDGE_PARTIAL"; do
    if [ -f "$guard_path" ]; then
      echo "FAIL: refusing to overwrite existing report: $guard_path" >&2
      echo "      set ALLOW_OVERWRITE=1 to overwrite it deliberately." >&2
      exit 1
    fi
  done
fi
# A scalar, not an array: on bash 3.2 (macOS's default) "${arr[@]}" on an empty array trips
# `set -u` before it ever gets used -- see run_h14_sweep.sh's header comment for the same
# pitfall. A single fixed, space-free flag word is safe to leave unquoted below.
JUDGE_ALLOW_FLAG=""
[ -n "$ALLOW_OVERWRITE" ] && JUDGE_ALLOW_FLAG="--allow-overwrite"

echo "=== H14 + $MODEL_LABEL (llama-server port $PORT) ==="

# Kill existing on port
lsof -ti :"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

# Start llama-server
echo "Starting llama-server..."
llama-server \
  --model "$GGUF" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --temp 0 \
  -ngl 999 \
  &>"/tmp/h14-${MODEL_LABEL}-llama.log" &
SERVER_PID=$!
echo "PID: $SERVER_PID"

# Wait for it
for i in $(seq 1 60); do
  sleep 2
  if curl -s "http://127.0.0.1:${PORT}/v1/models" > /dev/null 2>&1; then
    echo "Ready after ${i}x2s"
    break
  fi
  if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "Process died"
    cat "/tmp/h14-${MODEL_LABEL}-llama.log" | tail -5
    exit 1
  fi
done

# Quick test
echo "Quick test..."
curl -s --max-time 60 "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${MODEL_LABEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello\"}],\"max_tokens\":5,\"temperature\":0}" 2>&1 | head -c 200
echo ""

# Run evaluate-answers
echo "Running evaluate-answers..."
cd "$DIR" && uv run code-diver \
  --config "$CFG" \
  evaluate-answers \
  --dataset datasets/protogen_answer_cases_100.jsonl \
  --cases 100 \
  --context-files 4 --context-lines 160 \
  --workers 1 \
  --agentic-queries --query-count 4 --query-workers 4 \
  --agentic-query-search-strategy graph_file \
  --agentic-query-rerank \
  --output "$OUT" \
  --partial-output "$PARTIAL" \
  2>&1

echo "evaluate-answers exit: $?"

# Strict judge
if [ -f "$OUT" ]; then
  echo "Running strict judge..."
  cd "$DIR" && uv run python scripts/rejudge_answer_report.py \
    "$OUT" \
    --judge-config configs/explanation-judge-vertex-gemini31-flash-lite.yml \
    --judge-prompt prompts/code-answer-judge-strict.md \
    --output "$JUDGE_OUT" \
    --partial-output "$JUDGE_PARTIAL" \
    --workers 4 \
    $JUDGE_ALLOW_FLAG \
    2>&1
fi

# Print summary
if [ -f "$JUDGE_OUT" ]; then
  echo ""
  uv run python -c "
import json
s = json.load(open('$JUDGE_OUT'))
o = json.load(open('$OUT'))
sm = s.get('metrics', {})
om = o.get('metrics', {})
criteria = {k: v for k, v in sm.items() if k.startswith('judge_') and k != 'judge_duration_ms' and not k.startswith('judge_overall')}
print('  sum/24:', round(sum(criteria.values()), 2))
for k, v in sorted(criteria.items()):
    print(f'  {k}: {v:.2f}')
for k in ['file_hit','candidate_file_hit@1','context_file_hit','citation_path_valid_rate','token_f1','key_token_f1','bigram_f1','answer_duration_ms_mean']:
    print(f'  {k}: {om.get(k, \"?\")}')
print(f'  errors: {sum(1 for r in o.get(\"results\",[]) if r.get(\"error\"))}')
"
fi

# Kill server
kill "$SERVER_PID" 2>/dev/null || true
echo "=== Done: $MODEL_LABEL ==="
