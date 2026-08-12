#!/usr/bin/env bash
# Runs one H16 (retrieval depth) arm against a locally served model, then judges it.
# Adapted from scripts/run_h14_model.sh -- see that script's header for the rationale
# behind reading the port/model out of the config and not starting shared infra here.
set -euo pipefail

MODEL_LABEL="qwen35-4b"
JUDGE_LABEL="qwen35-9b"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
CASES="${CASES:-100}"
DATASET="${DATASET:-datasets/protogen_answer_cases_100.jsonl}"
JUDGE_WORKERS="${JUDGE_WORKERS:-2}"
CONTEXT_FILES="${CONTEXT_FILES:-10}"
CONTEXT_LINES="${CONTEXT_LINES:-160}"
ARM="${ARM:-}"

if [ -z "$ARM" ]; then
  echo "usage: ARM=<b|c|d> $(basename "$0")"
  echo "  ARM is required and must be one of: b, c, d"
  exit 2
fi

H14_CFG="$DIR/configs/context-awareness/protogen-h14-qwen35-4b-text-graph.yml"
H16_DEPTH_CFG="$DIR/configs/context-awareness/protogen-h16-qwen35-4b-depth.yml"
JUDGE_CFG="$DIR/configs/answer-judge-local-${JUDGE_LABEL}.yml"

QUERY_COUNT=4
RERANK_FLAG="--agentic-query-rerank"
case "$ARM" in
  b)
    CFG="$H16_DEPTH_CFG"
    ;;
  c)
    CFG="$H14_CFG"
    RERANK_FLAG=""
    ;;
  d)
    CFG="$H14_CFG"
    QUERY_COUNT=8
    ;;
  *)
    echo "FAIL: ARM must be one of 'b', 'c', 'd' (got '$ARM')"
    exit 2
    ;;
esac

[ -f "$CFG" ] || { echo "No config for arm '$ARM': $CFG"; exit 2; }
[ -f "$JUDGE_CFG" ] || { echo "No judge config: $JUDGE_CFG"; exit 2; }

MLX="$DIR/.venv-vllm-metal-official/bin/mlx_lm"
[ -x "$MLX" ] || { echo "mlx_lm not found at $MLX"; exit 1; }

# --- read port and model out of the configs themselves -----------------------------------
read_generation() {
  uv run --project "$DIR" python - "$1" <<'PY'
import re, sys, yaml
generation = (yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}).get("generation") or {}
url, model = str(generation.get("url") or ""), str(generation.get("model") or "")
port = re.search(r":(\d+)/", url)
if not (port and model):
    sys.exit(f"Config {sys.argv[1]} has no usable generation.url/model (url={url!r} model={model!r})")
print(port.group(1), model)
PY
}
read -r PORT MODEL <<<"$(read_generation "$CFG")"
read -r JUDGE_PORT JUDGE_MODEL <<<"$(read_generation "$JUDGE_CFG")"

# Non-default context budgets get a distinct output suffix so they never collide with (or
# overwrite) the baseline reports produced with the defaults below.
BUDGET_SUFFIX=""
if [ "$CONTEXT_FILES" != "4" ] || [ "$CONTEXT_LINES" != "160" ]; then
  BUDGET_SUFFIX="-cf${CONTEXT_FILES}-cl${CONTEXT_LINES}"
fi

OUT="$DIR/.code-diver/reports/protogen-h16-arm${ARM}-qwen35-4b-${CASES}${BUDGET_SUFFIX}.json"
PARTIAL="${OUT%.json}.partial.json"
# The judged-report path is derived FROM $OUT (not hand-built from separate variables) so it
# always carries every distinguishing suffix $OUT has -- see scripts/judge_report_naming.py
# for why: a hand-built path here (as this script used to have) is exactly what silently
# clobbered a 100-case judged baseline with a 10-case re-judge (the case-count suffix was
# dropped from the hand-built path but not from $OUT).
JUDGE_OUT="$(uv run --project "$DIR" python "$DIR/scripts/judge_report_naming.py" "$OUT" --judge-label "$JUDGE_LABEL")"
JUDGE_PARTIAL="$(uv run --project "$DIR" python "$DIR/scripts/judge_report_naming.py" "$OUT" --judge-label "$JUDGE_LABEL" --partial)"
mkdir -p "$(dirname "$OUT")" "$(dirname "$JUDGE_OUT")"

# Refuse to silently clobber an existing report -- or its .partial.json recovery sibling --
# from a prior run of this arm/budget/case-count. The .partial.json files are guarded too:
# the incident this fixes clobbered the strict-judge report's .partial.json alongside the
# final report, destroying the only recovery path.
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

echo "=== H16 arm $ARM ==="
echo "  config:    $CFG"
echo "  model:     $MODEL  (port $PORT)"
echo "  judge:     $JUDGE_MODEL  (port $JUDGE_PORT)"
echo "  cases:     $CASES from $DATASET"
echo "  context:   ${CONTEXT_FILES} files / ${CONTEXT_LINES} lines"
echo "  queries:   count=${QUERY_COUNT}, rerank=$([ -n "$RERANK_FLAG" ] && echo on || echo off)"
echo "  output:    $OUT"
echo "  judge out: $JUDGE_OUT"

# --- preflight: shared infrastructure ----------------------------------------------------
COLLECTION="$(uv run --project "$DIR" python -c "
import sys, yaml
print(((yaml.safe_load(open('$CFG', encoding='utf-8')) or {}).get('storage') or {}).get('qdrant', {}).get('collection', ''))
")"
curl -sf --max-time 5 http://127.0.0.1:6333/healthz >/dev/null 2>&1 || {
  echo "FAIL: Qdrant is not answering on 127.0.0.1:6333."
  echo "      Start it (OrbStack/Docker) before running the sweep."
  exit 1
}
curl -sf --max-time 5 "http://127.0.0.1:6333/collections/${COLLECTION}" >/dev/null 2>&1 || {
  echo "FAIL: Qdrant has no collection '${COLLECTION}' -- the index has not been built."
  exit 1
}
curl -sf --max-time 5 http://127.0.0.1:8001/v1/models >/dev/null 2>&1 || {
  echo "FAIL: embedding server is not answering on 127.0.0.1:8001."
  echo "      VLLM_HOST_IP=127.0.0.1 GLOO_SOCKET_IFNAME=lo0 VLLM_METAL_MEMORY_FRACTION=0.55 \\"
  echo "        .venv-vllm-metal-official/bin/vllm serve mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ \\"
  echo "        --runner pooling --host 127.0.0.1 --port 8001 --max-model-len 512"
  exit 1
}
GRAPH="$(uv run --project "$DIR" python -c "
import yaml
print(((yaml.safe_load(open('$CFG', encoding='utf-8')) or {}).get('graph') or {}).get('artifact', ''))
")"
[ -f "$DIR/$GRAPH" ] || { echo "FAIL: graph artifact missing: $GRAPH"; exit 1; }
echo "  preflight: qdrant/${COLLECTION}, embeddings:8001, graph artifact -- ok"

# --- serve the model ---------------------------------------------------------------------
SERVER_PID=""
serve() {
  local port="$1" model="$2" log="$3"
  lsof -ti :"$port" 2>/dev/null | xargs kill -9 2>/dev/null || true
  sleep 2
  "$MLX" server --model "$model" --host 127.0.0.1 --port "$port" &>"$log" &
  SERVER_PID=$!
  for i in $(seq 1 150); do
    sleep 2
    # /v1/models is not a readiness signal: mlx_lm answers it 200 before the weights load
    # and keeps answering it after loading FAILS. Probing a real completion is the only
    # honest check.
    if curl -sf --max-time 20 -H 'Content-Type: application/json' \
        -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":1,\"stream\":false}" \
        "http://127.0.0.1:${port}/v1/chat/completions" >/dev/null 2>&1; then
      echo "  server ready on :$port after $((i * 2))s"
      return 0
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "FAIL: server died while loading $model"; tail -20 "$log"; exit 1
    fi
    if grep -q "not supported" "$log" 2>/dev/null; then
      echo "FAIL: mlx_lm cannot load $model"; grep -m1 "not supported" "$log"; exit 1
    fi
  done
  echo "FAIL: server on :$port did not come up in 300s"; tail -20 "$log"; exit 1
}
stop_server() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
}
trap stop_server EXIT

echo "Starting generation server..."
serve "$PORT" "$MODEL" "/tmp/h16-arm${ARM}${BUDGET_SUFFIX}-server.log"

echo "Running evaluate-answers ($CASES cases)..."
EVAL_EXIT=0
cd "$DIR" && uv run code-diver \
  --config "$CFG" \
  evaluate-answers \
  --dataset "$DATASET" \
  --cases "$CASES" \
  --context-files "$CONTEXT_FILES" --context-lines "$CONTEXT_LINES" \
  --workers 1 \
  --agentic-queries --query-count "$QUERY_COUNT" --query-workers 4 \
  --agentic-query-search-strategy graph_file \
  $RERANK_FLAG \
  --output "$OUT" \
  --partial-output "$PARTIAL" 2>&1 || EVAL_EXIT=$?
echo "evaluate-answers exit: $EVAL_EXIT"
stop_server
sleep 3

# --- judge (secondary signal) ------------------------------------------------------------
if [ -f "$OUT" ]; then
  echo "Starting judge server ($JUDGE_LABEL)..."
  serve "$JUDGE_PORT" "$JUDGE_MODEL" "/tmp/h16-arm${ARM}${BUDGET_SUFFIX}-judge-${JUDGE_LABEL}-server.log"
  echo "Running strict judge..."
  cd "$DIR" && uv run python scripts/rejudge_answer_report.py \
    "$OUT" \
    --judge-config "$JUDGE_CFG" \
    --judge-prompt prompts/code-answer-judge-strict.md \
    --output "$JUDGE_OUT" \
    --partial-output "$JUDGE_PARTIAL" \
    --workers "$JUDGE_WORKERS" \
    $JUDGE_ALLOW_FLAG 2>&1 || echo "WARN: judge failed; deterministic metrics below still stand"
  stop_server
fi

# --- summary -----------------------------------------------------------------------------
cd "$DIR" && uv run python scripts/summarize_h14_run.py "$OUT" --judge-report "$JUDGE_OUT" --label "h16-arm${ARM}"
echo "=== Done: arm $ARM ==="
