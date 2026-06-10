# Judge Testing Plan - June 10, 2026

## Executive Summary

**Objective**: Test and compare 4 judge models on existing explanation reports to determine optimal judge selection for code explanation evaluation.

**Test Approach**: Use `rejudge_explanation_report.py` to re-evaluate existing predictions with different judge models, avoiding regeneration of explanations.

**Dataset**: CodeXGLUE code-to-text-python (100 cases)

**Existing Baseline**: All current reports use Vertex Gemini 3.1 Flash Lite as judge

---

## Judge Candidates Identified

### 1. **Vertex Gemini 3.1 Flash Lite** (BASELINE - Already Tested)
- **Config**: `configs/explanation-judge-vertex-gemini31-flash-lite.yml`
- **Provider**: Vertex AI
- **Model**: `gemini-3.1-flash-lite`
- **Status**: ✅ Already used in all current reports
- **Characteristics**: Cloud-based, fast, production-quality

### 2. **Gemma 4 E2B (2.5B)** - LOCAL
- **Config**: `configs/explanation-judge-gemma4-e2b.yml`
- **Provider**: OpenAI-compatible local (port 8012)
- **Model**: `mlx-community/gemma-4-e2b-it-4bit`
- **Status**: ⏳ Needs testing
- **Characteristics**: Smallest local model, fastest inference, lowest resource usage

### 3. **Gemma 4 E4B (4.3B)** - LOCAL
- **Config**: `configs/explanation-judge-gemma4-e4b.yml`
- **Provider**: OpenAI-compatible local (port 8013)
- **Model**: `mlx-community/gemma-4-e4b-it-4bit`
- **Status**: ⏳ Needs testing
- **Characteristics**: Mid-size local model, balance of speed and quality

### 4. **Qwen 3.5 9B** - LOCAL
- **Config**: `configs/explanation-judge-qwen35-9b.yml`
- **Provider**: OpenAI-compatible local (port 8014)
- **Model**: `mlx-community/Qwen3.5-9B-MLX-4bit`
- **Status**: ⏳ Needs testing
- **Characteristics**: Largest local model, highest quality potential, slowest

---

## Test Data Selection

### Available Completed Reports (100 cases each):

1. ✅ **code-explainer-ex1-gemma-e2b** (417KB) - Gemma E2B explainer
2. ✅ **code-explainer-ex2-gemma-e4b** (603KB) - Gemma E4B explainer
3. ✅ **code-explainer-ex3-gemma-e2b-rerun** (405KB) - Gemma E2B rerun
4. ✅ **code-explainer-ex4-gemma-e4b-rerun** (601KB) - Gemma E4B rerun
5. ✅ **code-explainer-gemini31-flash-lite** (524KB) - Gemini explainer
6. ✅ **code-explainer-gemma26** (537KB) - Gemma 26B explainer
7. ✅ **code-explainer-qwen35-4b** (540KB) - Qwen 3.5 4B explainer

### Recommended Test Report:
**`code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json`**

**Rationale**:
- Largest file (603KB) = richest content
- Gemma E4B explainer = balanced complexity
- Already judged with baseline = easy comparison
- Not a "rerun" = clean initial evaluation

---

## Testing Approach

### Method: Post-hoc Re-judging
- Use `scripts/rejudge_explanation_report.py`
- Input: Existing report with predictions
- Process: Extract predictions → judge with new model → save new report
- Benefit: No need to regenerate explanations (fast, consistent)

### Judge Prompt:
- **File**: `prompts/code-explanation-judge.md`
- **Consistency**: Same prompt for all judges
- **Metrics**: 7 dimensions + overall score

### Dataset Reference:
- **File**: `.code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl`
- **Cases**: 100 Python code snippets with reference explanations

---

## Test Execution Plan

### Prerequisites

1. **Verify dataset exists**:
   ```bash
   ls -lh .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl
   ```

2. **Verify test report exists**:
   ```bash
   ls -lh .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json
   ```

3. **Create output directory**:
   ```bash
   mkdir -p .code-diver/reports/judge-comparison
   ```

### Test Commands

#### Test 1: Gemma 4 E2B (2.5B) Judge
```bash
# 1. Start local server (in separate terminal)
.venv-vllm-metal-official/bin/mlx_lm.server \
  --model mlx-community/gemma-4-e2b-it-4bit \
  --host 127.0.0.1 \
  --port 8012 \
  --max-tokens 2048 \
  --temp 0 \
  --prompt-concurrency 1 \
  --decode-concurrency 1 \
  --chat-template-args '{"enable_thinking": false}'

# 2. Run rejudge (in main terminal)
uv run python scripts/rejudge_explanation_report.py \
  .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json \
  --dataset .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl \
  --judge-config configs/explanation-judge-gemma4-e2b.yml \
  --judge-prompt prompts/code-explanation-judge.md \
  --output .code-diver/reports/judge-comparison/ex2-rejudged-gemma4-e2b.json \
  --partial-output .code-diver/reports/judge-comparison/ex2-rejudged-gemma4-e2b.partial.json \
  --workers 1
```
**Estimated time**: ~8-12 minutes (100 cases, ~5-7s per case)

---

#### Test 2: Gemma 4 E4B (4.3B) Judge
```bash
# 1. Stop previous server, start new server
.venv-vllm-metal-official/bin/mlx_lm.server \
  --model mlx-community/gemma-4-e4b-it-4bit \
  --host 127.0.0.1 \
  --port 8013 \
  --max-tokens 2048 \
  --temp 0 \
  --prompt-concurrency 1 \
  --decode-concurrency 1 \
  --chat-template-args '{"enable_thinking": false}'

# 2. Run rejudge
uv run python scripts/rejudge_explanation_report.py \
  .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json \
  --dataset .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl \
  --judge-config configs/explanation-judge-gemma4-e4b.yml \
  --judge-prompt prompts/code-explanation-judge.md \
  --output .code-diver/reports/judge-comparison/ex2-rejudged-gemma4-e4b.json \
  --partial-output .code-diver/reports/judge-comparison/ex2-rejudged-gemma4-e4b.partial.json \
  --workers 1
```
**Estimated time**: ~10-15 minutes (100 cases, ~6-9s per case)

---

#### Test 3: Qwen 3.5 9B Judge
```bash
# 1. Stop previous server, start new server
.venv-vllm-metal-official/bin/mlx_lm.server \
  --model mlx-community/Qwen3.5-9B-MLX-4bit \
  --host 127.0.0.1 \
  --port 8014 \
  --max-tokens 2048 \
  --temp 0 \
  --prompt-concurrency 1 \
  --decode-concurrency 1 \
  --chat-template-args '{"enable_thinking": false}'

# 2. Run rejudge
uv run python scripts/rejudge_explanation_report.py \
  .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json \
  --dataset .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl \
  --judge-config configs/explanation-judge-qwen35-9b.yml \
  --judge-prompt prompts/code-explanation-judge.md \
  --output .code-diver/reports/judge-comparison/ex2-rejudged-qwen35-9b.json \
  --partial-output .code-diver/reports/judge-comparison/ex2-rejudged-qwen35-9b.partial.json \
  --workers 1
```
**Estimated time**: ~15-20 minutes (100 cases, ~9-12s per case)

---

#### Test 4: Vertex Gemini (Baseline Reference)
```bash
# No server needed (cloud-based)
uv run python scripts/rejudge_explanation_report.py \
  .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json \
  --dataset .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl \
  --judge-config configs/explanation-judge-vertex-gemini31-flash-lite.yml \
  --judge-prompt prompts/code-explanation-judge.md \
  --output .code-diver/reports/judge-comparison/ex2-rejudged-vertex-gemini31.json \
  --partial-output .code-diver/reports/judge-comparison/ex2-rejudged-vertex-gemini31.partial.json \
  --workers 8
```
**Estimated time**: ~3-5 minutes (100 cases, parallel workers, cloud speed)

---

## Analysis & Comparison

### Step 1: Extract Metrics Summary
```bash
uv run python scripts/summarize_explainer_matrix.py --markdown \
  .code-diver/reports/judge-comparison/ex2-rejudged-*.json
```

### Step 2: Compare Key Metrics

**Metrics to Compare**:
1. **Judge Overall Score** - Primary quality indicator
2. **Judge Clarity** - How well judge assesses clarity
3. **Judge Completeness** - Coverage assessment quality
4. **Judge Groundedness** - Code faithfulness checks
5. **Judge API Contract** - Technical accuracy
6. **Judge Behavior Accuracy** - Functional correctness
7. **Judge Purpose Accuracy** - Intent understanding

**Performance Metrics**:
- **Duration (ms)** - Speed comparison
- **Tokens/case** - Cost comparison
- **Judge error count** - Reliability

### Step 3: Statistical Analysis

Compare distributions:
- Mean scores per judge
- Standard deviation (consistency)
- Correlation with baseline (Vertex Gemini)
- Score variance per case

### Step 4: Qualitative Review

Select 5-10 cases with high disagreement:
- Read original code + explanation
- Review all 4 judge outputs
- Assess which judge reasoning is most accurate
- Identify systematic biases

---

## Decision Criteria

### Primary Questions:
1. **Accuracy**: Which judge aligns best with human expectations?
2. **Consistency**: Which judge shows lowest variance?
3. **Cost**: Local vs. cloud trade-offs
4. **Speed**: Acceptable latency for workflow
5. **Reliability**: Error rates and failure modes

### Trade-off Matrix:

| Judge | Quality | Speed | Cost | Reliability | Verdict |
|---|---|---|---|---|---|
| Vertex Gemini | Baseline | Fast | $$ | High | Production default |
| Gemma E2B | ? | Fastest | Free | ? | Budget option |
| Gemma E4B | ? | Fast | Free | ? | Balanced local |
| Qwen 9B | ? | Slowest | Free | ? | Quality local |

---

## Expected Outcomes

### Success Criteria:
- ✅ All 4 judges complete 100-case evaluation
- ✅ Error rate < 5% per judge
- ✅ Metrics show meaningful differentiation
- ✅ Clear recommendation emerges

### Deliverables:
1. 4 rejudged reports in `.code-diver/reports/judge-comparison/`
2. Metrics comparison table (markdown)
3. Statistical analysis summary
4. Recommendation document with trade-offs

### Next Steps After Testing:
- If local judge competitive: Update default configs
- If Vertex superior: Document cost justification
- If mixed results: Define use-case specific routing
- Update documentation with judge selection guide

---

## Total Estimated Time

- **Setup & verification**: 5 minutes
- **Test 1 (Gemma E2B)**: 12 minutes
- **Test 2 (Gemma E4B)**: 15 minutes
- **Test 3 (Qwen 9B)**: 20 minutes
- **Test 4 (Vertex)**: 5 minutes
- **Analysis**: 15 minutes

**Total Sequential**: ~72 minutes (~1.2 hours)
**Total with parallelization**: ~30 minutes (if running multiple judges on different machines)

---

## Risk Mitigation

### Potential Issues:

1. **Local server crashes**
   - Mitigation: Use `--partial-output` to save progress
   - Recovery: Restart from partial results

2. **JSON schema errors**
   - Mitigation: All configs use `response_format: json_schema`
   - Recovery: Increase retry attempts in config

3. **Token limit exceeded**
   - Mitigation: All judges configured for 2048 max tokens
   - Note: Judge prompts are ~1200 tokens, outputs ~300 tokens

4. **Vertex auth issues**
   - Mitigation: Verify `gcloud auth application-default login`
   - Alternative: Use service account key

---

## Appendix: Configuration Summary

### Port Mapping:
- 8012: Gemma 4 E2B / Qwen 3.5 4B (shared, switch as needed)
- 8013: Gemma 4 E4B
- 8014: Qwen 3.5 9B
- 8015: Gemma 4 12B (not judge, but available)
- 8016: Gemma 4 26B (not judge, but available)

### MLX Server Common Args:
```bash
--max-tokens 2048
--temp 0
--prompt-concurrency 1
--decode-concurrency 1
--chat-template-args '{"enable_thinking": false}'
```

### Judge Config Template:
```yaml
generation:
  provider: openai_compatible / vertex
  model: <model-id>
  url: http://127.0.0.1:<port>/v1/chat/completions  # local only
  temperature: 0
  max_tokens: 2048
  response_format: json_schema / json_object
  timeout_ms: 120000-240000
  retry_attempts: 2
```

---

## Quick Start Commands

```bash
# 1. Verify prerequisites
ls -lh .code-diver/benchmarks/codexglue-code-to-text-python/explanations.jsonl
ls -lh .code-diver/reports/code-explainer-ex2-gemma-e4b-vertex-gemini31-flash-lite-judge-100.json
mkdir -p .code-diver/reports/judge-comparison

# 2. Run all tests (requires manual server switching between tests)
# See detailed commands in "Test Execution Plan" section above

# 3. Compare results
uv run python scripts/summarize_explainer_matrix.py --markdown \
  .code-diver/reports/judge-comparison/ex2-rejudged-*.json

# 4. Review detailed outputs
cat .code-diver/reports/judge-comparison/*.json | jq '.metrics'
```

---

## Status Tracking

- [ ] Prerequisites verified
- [ ] Test 1: Gemma E2B judge complete
- [ ] Test 2: Gemma E4B judge complete  
- [ ] Test 3: Qwen 9B judge complete
- [ ] Test 4: Vertex Gemini reference complete
- [ ] Metrics comparison generated
- [ ] Statistical analysis complete
- [ ] Qualitative review complete
- [ ] Final recommendation documented
