# Session — Candidate Testing Status & Recovery (2026-06-10)

## Situation

User reported: "we were testing candidates but something went wrong, codex quota went out and probably processes are dead"

## Investigation Results

### 1. Process Status
- ✅ **Stuck process killed**: PID 21042 (H14 smoke test stuck for 1h 25min)
- ✅ **Embedding server restarted**: Qwen3-Embedding-0.6B on port 8001
- ✅ **LLM server running**: Gemma 26B on port 8016
- **No quota issues found**: Logs are empty (rotated today), no rate limit errors

### 2. Root Cause
**Embedding server was not running** — the H14 test process was stuck waiting for embeddings on port 8001, which explains the uninterruptible wait state.

### 3. Candidate Testing Status

#### ✅ **Completed** (3 configs)
- `protogen-h12a-context-artifact-vertex.yml` — 100/100 cases (Jun 9)
- `protogen-h12b-doc-vector-lane-vertex.yml` — 100/100 cases (Jun 9)
- `protogen-h13-gemma26-agentic-doc-graph.yml` — 100/100 cases (Jun 10 04:24)

#### ⚠️ **Incomplete** (1 config, 3 failed attempts)
- `protogen-h14-gemma26-text-graph.yml`:
  - Attempt 1: Interrupted at 81/100 (Jun 10 10:13, server crash)
  - Attempt 2: Stopped at 17/100 (Jun 10 11:51, manual stop)
  - Attempt 3: Stuck in reindex (killed by us)

#### ❌ **Untested** (7 configs)
- H7 series: 3 configs (no-context, readme-summary variants)
- H8 series: 2 configs (file GraphRAG)
- H10 series: 2 configs (graph-first retrieval)

## Next Steps

### Immediate Actions (In Progress)

1. ✅ **Kill stuck process** — DONE
2. ✅ **Start embedding server** — DONE
3. **Run H14 full test** — Ready to start (6.9 hours estimated)

### Command for H14 Full Run

```bash
uv run code-diver --config configs/context-awareness/protogen-h14-gemma26-text-graph.yml \
  evaluate-answers \
  --dataset datasets/protogen_answer_cases_100.jsonl \
  --cases 100 \
  --context-files 4 \
  --context-lines 160 \
  --workers 1 \
  --agentic-queries \
  --query-count 4 \
  --query-workers 4 \
  --agentic-query-search-strategy graph_file \
  --agentic-query-rerank \
  --output .code-diver/reports/protogen-h14-gemma26-text-graph-100-final.json \
  --partial-output .code-diver/reports/protogen-h14-gemma26-text-graph-100-final.partial.json
```

### After H14 Completes

4. **Run meta-judge comparison** with random order:

```bash
python scripts/meta_judge_explainer_candidates.py \
  --dataset datasets/protogen_answer_cases_100.jsonl \
  --judge-config configs/explanation-judge-vertex-gemini31-flash-lite.yml \
  --candidate h12a=.code-diver/reports/protogen-h12a-context-artifact-vertex-100.json \
  --candidate h12b=.code-diver/reports/protogen-h12b-doc-vector-lane-vertex-100.json \
  --candidate h13=.code-diver/reports/protogen-h13-gemma26-agentic-doc-graph-100.json \
  --candidate h14=.code-diver/reports/protogen-h14-gemma26-text-graph-100-final.json \
  --cases 100 \
  --output .code-diver/reports/protogen-context-awareness-meta-judge.json \
  --partial-output .code-diver/reports/protogen-context-awareness-meta-judge.partial.json \
  --workers 8 \
  --seed 17 \
  --bootstrap-samples 2000 \
  --markdown
```

**Key feature**: `--seed 17` ensures reproducible random ordering. The script uses `balanced_permutations()` to randomize candidate order (A-Z labels) per case and balance position bias.

5. **Decide on H7/H8/H10 backlog** — check if still relevant or superseded by H12/H13/H14

## Meta-Judge Details

**Script**: `scripts/meta_judge_explainer_candidates.py`

**Purpose**: Blind listwise comparison of multiple candidate explanations
- Randomizes candidate order per case (balanced permutations)
- Labels candidates A-Z (blind judging)
- Parallel workers for efficiency
- Bootstrap confidence intervals
- Incremental partial saves

**Related**: `scripts/summarize_explainer_matrix.py` generates comparison tables with CI from multiple reports

## Files Created
- `.session/2026-06-10_candidate-testing-investigation.md` — Initial investigation
- `.session/2026-06-10_h14-resume.md` — Server startup details
- `.session/2026-06-10_candidate-testing-status.md` — This file

## Current Blockers

**NONE** — All systems operational, ready to proceed with H14 test.
