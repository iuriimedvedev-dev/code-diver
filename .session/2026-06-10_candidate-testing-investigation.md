# Candidate Testing Investigation - 2026-06-10

## Summary

Investigation of current candidate testing processes for code-diver evaluation experiments.

## Currently Running Process

**PID: 21042** (Running for ~1h 25min, Status: U - uninterruptible wait)

```bash
/Users/iurii.medvedev/Work/code-diver/.venv/bin/python3 \
  /Users/iurii.medvedev/Work/code-diver/.venv/bin/code-diver \
  --config configs/context-awareness/protogen-h14-gemma26-text-graph-embeddinggemma.yml \
  evaluate-answers \
  --dataset datasets/protogen_answer_cases_100.jsonl \
  --cases 2 \
  --context-files 4 \
  --context-lines 160 \
  --workers 1 \
  --agentic-queries \
  --query-count 4 \
  --query-workers 4 \
  --agentic-query-search-strategy graph_file \
  --agentic-query-rerank \
  --output .code-diver/reports/protogen-h14-embeddinggemma-gemma26-text-graph-smoke-2.json \
  --partial-output .code-diver/reports/protogen-h14-embeddinggemma-gemma26-text-graph-smoke-2.partial.json \
  --reindex
```

**Status**: Smoke test run (2 cases only) with embedding model variant.
**Output**: No partial file created yet, suggesting it may be stuck in reindexing phase.

## Recent Test Runs

### H13: Agentic Doc Graph (COMPLETED)
- **File**: `protogen-h13-gemma26-agentic-doc-graph-100.json`
- **Status**: ✅ Completed 100/100 cases (Jun 10 04:24)
- **Results**: 
  - file_hit: 0.8200
  - file_recall: 0.7500
  - context_file_hit: 0.7900
  - 4 timeouts

### H14: Text Graph Context 

**Run 1 - INTERRUPTED**
- **File**: `protogen-h14-gemma26-text-graph-100.partial.json`
- **Status**: ⚠️ Interrupted at 81/100 cases (Jun 10 10:13)
- **Reason**: Local Gemma server stopped
- **Results at interruption**:
  - file_hit: 0.8462
  - file_recall: 0.7756
  - context_file_hit: 0.8462
  - 3 timeouts

**Run 2 - INCOMPLETE**
- **File**: `protogen-h14-gemma26-text-graph-100-rerun.partial.json`
- **Status**: ⏸️ Stopped at 17/100 cases (Jun 10 11:51)
- **Reason**: Unknown - appears abandoned

**Run 3 - CURRENT (Smoke Test)**
- **File**: `protogen-h14-embeddinggemma-gemma26-text-graph-smoke-2.*`
- **Status**: 🔄 Running but likely stuck in reindexing (no partial output after 1h 25min)
- **Config Change**: Using `google/embeddinggemma-300m` instead of Qwen3-Embedding

## Test Candidate Configurations

Found 13 configurations in `configs/context-awareness/`:

**H7 Series**: Early experiments
- protogen-h7-gemma26-no-context
- protogen-h7-gemma26-readme-summary
- protogen-h7-gemma-e2b-readme-summary

**H8 Series**: 
- protogen-h8-gemma26-no-context
- protogen-h8-gemma26-readme-summary

**H10 Series**:
- protogen-h10-gemma26-no-context
- protogen-h10-gemma26-readme-summary

**H12 Series**: Dual-lane docs/code (COMPLETED)
- protogen-h12-dual-lane-gemma26
- protogen-h12a-context-artifact-vertex ✅ (100 cases)
- protogen-h12b-doc-vector-lane-vertex ✅ (100 cases)

**H13 Series**: Agentic doc graph (COMPLETED)
- protogen-h13-gemma26-agentic-doc-graph ✅ (100 cases)

**H14 Series**: Text graph context (IN PROGRESS)
- protogen-h14-gemma26-text-graph (2 incomplete runs)
- protogen-h14-gemma26-text-graph-embeddinggemma (smoke test running)

## Completion Status

| Hypothesis | Config | Cases | Status | File |
|------------|--------|-------|--------|------|
| H12a | context-artifact-vertex | 100 | ✅ Complete | protogen-h12a-context-artifact-vertex-100.json |
| H12b | doc-vector-lane-vertex | 100 | ✅ Complete | protogen-h12b-doc-vector-lane-vertex-100.json |
| H13 | agentic-doc-graph | 100 | ✅ Complete | protogen-h13-gemma26-agentic-doc-graph-100.json |
| H14 | text-graph (run1) | 81 | ⚠️ Interrupted | protogen-h14-gemma26-text-graph-100.partial.json |
| H14 | text-graph (run2) | 17 | ⏸️ Stopped | protogen-h14-gemma26-text-graph-100-rerun.partial.json |
| H14 | embeddinggemma smoke | 0 | 🔄 Running/Stuck | No partial output yet |

## Quota/Error Information

**No quota or rate limit errors found** in recent logs:
- `.code-diver/runtime/logs/gemma26-chat-server-8016-current.log` (empty, rotated Jun 10 12:46)
- `.code-diver/runtime/logs/embeddinggemma-server-8001.log` (empty, rotated Jun 10 12:46)
- `.code-diver/runtime/logs/embedding-server.log` (empty, rotated Jun 10 12:45)

## Test Artifacts Locations

**Reports**: `.code-diver/reports/`
- Completed results: `*.json` (non-partial)
- In-progress: `*.partial.json`
- ~336 files total in reports directory

**Configurations**: `configs/context-awareness/*.yml`
**Dataset**: `datasets/protogen_answer_cases_100.jsonl` (100 cases)
**Documentation**: 
- `docs/hypotheses/h14-text-graph-context.md`
- `docs/local-h13-h14-gemma26-2026-06-10.md`

**Runtime tracking**:
- PID file: `.code-diver/runtime/gemma26-agentic-eval.pid` (contains: 99363 - stale PID)

## Key Findings

1. **H14 testing incomplete**: The main H14 hypothesis has 2 incomplete runs and 1 potentially stuck smoke test
2. **Process appears stuck**: Current process running 1h 25min with `--reindex` flag but no partial output suggests it's stuck in reindexing phase
3. **No quota issues**: No API rate limits or quota errors detected
4. **Clean baseline exists**: H13 provides a complete 100-case baseline for comparison
5. **Server stability issue**: Previous H14 run interrupted when "local Gemma server stopped"

## Recommendations

1. **Check current process**: The running process (PID 21042) may be stuck - consider investigating its progress or terminating
2. **Resume H14 main run**: Complete the full 100-case H14 text-graph evaluation (currently at 17/100)
3. **Validate server health**: Check local Gemma 26B server stability before long runs
4. **Document run strategy**: Clarify the testing queue and priority for remaining H-series experiments (H7, H8, H10 configs appear untested)
