# Judge Test Coverage Analysis

**Date**: 2026-06-10
**Analysis**: Test coverage for Judge metrics in scripts/summarize_explainer_matrix.py

## Metrics Tracked by Script

### Judge Keys (8 metrics)
1. `judge_overall` - Weighted overall score
2. `judge_purpose_accuracy` - Purpose accuracy (weight: 0.18)
3. `judge_behavior_accuracy` - Behavior/control-flow accuracy (weight: 0.22)
4. `judge_api_contract` - Inputs/outputs/side effects/errors (weight: 0.15)
5. `judge_groundedness` - Groundedness/hallucination control (weight: 0.18)
6. `judge_specificity` - Code-specific detail (weight: 0.12)
7. `judge_completeness` - Coverage of important behavior (weight: 0.10)
8. `judge_clarity` - Developer readability (weight: 0.05)

### Overlap Keys (3 metrics)
1. `token_f1` - Token F1 score
2. `key_token_f1` - Key token F1 (excluding stop words)
3. `bigram_f1` - Bigram F1 score

### Error Tracking (3 metrics)
1. `generation_errors` - Count of generation failures
2. `empty_explanations` - Count of empty predictions
3. `judge_errors` - Count of judge evaluation failures

## Coverage Matrix

### test_explanation_evaluator.py

| Test Function | Coverage |
|---------------|----------|
| `test_explanation_metrics_score_token_overlap()` | ✅ `token_f1`, `key_token_recall` |
| `test_code_explanation_evaluator_generates_metrics_and_judge_scores()` | ✅ `token_f1`, `judge_overall`, `judge_behavior_accuracy` |
| `test_explanation_judge_uses_custom_prompt_file()` | ✅ `judge_overall` (all criteria scored at 4) |
| `test_code_explanation_evaluator_records_malformed_case_and_continues()` | ✅ `generation_errors` (error_count) |
| `test_code_explanation_evaluator_treats_empty_explanation_as_generation_error()` | ✅ `empty_explanations` (error_count, empty explanation) |
| `test_code_explanation_evaluator_can_run_cases_concurrently_in_dataset_order()` | Usage tracking only |

**Metrics Covered**:
- ✅ `judge_overall` - Multiple tests
- ✅ `judge_behavior_accuracy` - One test (line 107)
- ✅ `token_f1` - Multiple tests
- ✅ `key_token_recall` - One test (not key_token_f1, but related)
- ✅ `generation_errors` - Two tests (error_count tracking)
- ✅ `empty_explanations` - One test (line 189-191)
- ⚠️ `judge_errors` - NOT directly tested (judge_error_count referenced line 69 but no test validates it)

**Metrics NOT Covered**:
- ❌ `judge_purpose_accuracy` - No explicit test
- ❌ `judge_api_contract` - Mentioned in line 111 but not asserted
- ❌ `judge_groundedness` - Not tested
- ❌ `judge_specificity` - Not tested
- ❌ `judge_completeness` - Not tested
- ❌ `judge_clarity` - Not tested
- ❌ `bigram_f1` - Not tested
- ❌ `key_token_f1` - Not tested (key_token_recall is tested but not f1)

### test_answer_evaluator.py

| Test Function | Coverage |
|---------------|----------|
| `test_answer_evaluator_searches_reads_answers_and_judges()` | ✅ `judge_overall` (line 234), file metrics, citation metrics |
| `test_answer_evaluator_preserves_retrieval_metrics_when_answer_json_breaks()` | ✅ `generation_errors` (error_count line 274) |
| `test_answer_judge_rubric_computes_weighted_overall()` | ✅ `judge_overall` (all answer criteria at 4) |
| `test_answer_report_judge_scores_saved_rows_with_stored_context()` | ✅ `judge_overall`, `judge_error_count` (line 684) |

**Note**: Answer evaluator tests cover Answer-specific judge criteria (answer_correctness, evidence_grounding, etc.), which are DIFFERENT from Explanation judge criteria tracked in summarize_explainer_matrix.py.

**Metrics Covered**:
- ✅ `judge_overall` - Multiple tests (but for Answer domain, not Explanation)
- ✅ `generation_errors` - One test
- ✅ `judge_errors` - One test (line 684)

## Source Code Validation

### Explanation Judge Metrics Production
**File**: `src/code_diver/explanation/explanation_judge_rubric.py:9-17`

The rubric produces these metrics via `score()` method (lines 40-44):
```python
flat_scores[f"judge_{criterion.id}"] = score
flat_scores["judge_overall"] = overall
```

**Confirmed**: All 8 judge_* metrics ARE produced by ExplanationJudgeRubric.

### Overlap Metrics Production
**File**: `src/code_diver/explanation/explanation_metrics.py:32-52`

The `score()` method produces (lines 40-52):
- `token_precision`, `token_recall`, `token_f1`
- `key_token_precision`, `key_token_recall`, `key_token_f1`
- `bigram_precision`, `bigram_recall`, `bigram_f1`
- `prediction_tokens`, `reference_tokens`

**Confirmed**: All 3 OVERLAP_KEYS metrics ARE produced by ExplanationMetrics.

### Error Tracking Production
**Files**:
- `scripts/summarize_explainer_matrix.py:54-69`
- Evaluator implementations

**Confirmed**:
- `empty_explanations` - Computed in script (lines 54-58)
- `generation_errors` - From payload.error_count or computed (line 59)
- `judge_errors` - From payload.judge_error_count or computed (line 69)

## Missing Test Coverage

### Critical Gaps (Individual Judge Criteria)

1. **judge_purpose_accuracy** - No test validates this specific criterion
   - Weight: 0.18 (2nd highest)
   - Impact: High

2. **judge_api_contract** - No test validates this specific criterion
   - Weight: 0.15
   - Impact: Medium-High

3. **judge_groundedness** - No test validates this specific criterion
   - Weight: 0.18 (2nd highest)
   - Impact: High

4. **judge_specificity** - No test validates this specific criterion
   - Weight: 0.12
   - Impact: Medium

5. **judge_completeness** - No test validates this specific criterion
   - Weight: 0.10
   - Impact: Medium

6. **judge_clarity** - No test validates this specific criterion
   - Weight: 0.05
   - Impact: Low

### Moderate Gaps (Overlap Metrics)

7. **bigram_f1** - Not tested in test_explanation_evaluator.py
   - Listed in OVERLAP_KEYS
   - Impact: Medium

8. **key_token_f1** - Not tested (key_token_recall is tested)
   - Listed in OVERLAP_KEYS
   - Impact: Medium

### Minor Gaps (Error Tracking)

9. **judge_errors** - No test validates judge_error_count is properly recorded
   - Test exists in answer_evaluator (line 684) but not explanation_evaluator
   - Impact: Low-Medium

## Recommendations

### Priority 1 - High-Weight Judge Criteria Tests

Add tests to `test_explanation_evaluator.py`:

```python
def test_explanation_judge_scores_all_criteria_separately() -> None:
    """Validate that all judge criteria are computed and stored correctly."""
    case = ExplanationCase(...)
    prediction_provider = FakeProvider([...])
    judge_provider = FakeProvider([
        json.dumps({
            "criteria": {
                "purpose_accuracy": {"score": 4, "answer": "yes", "evidence": "..."},
                "behavior_accuracy": {"score": 3, "answer": "mostly", "evidence": "..."},
                "api_contract": {"score": 2, "answer": "partially", "evidence": "..."},
                "groundedness": {"score": 4, "answer": "yes", "evidence": "..."},
                "specificity": {"score": 3, "answer": "mostly", "evidence": "..."},
                "completeness": {"score": 3, "answer": "mostly", "evidence": "..."},
                "clarity": {"score": 4, "answer": "yes", "evidence": "..."},
            },
            "rationale": "...",
        })
    ])
    
    report = CodeExplanationEvaluator(
        prediction_provider,
        judge=ExplanationJudge(judge_provider),
    ).evaluate([case])
    
    # Validate individual criteria
    assert report["results"][0]["metrics"]["judge_purpose_accuracy"] == 4.0
    assert report["results"][0]["metrics"]["judge_behavior_accuracy"] == 3.0
    assert report["results"][0]["metrics"]["judge_api_contract"] == 2.0
    assert report["results"][0]["metrics"]["judge_groundedness"] == 4.0
    assert report["results"][0]["metrics"]["judge_specificity"] == 3.0
    assert report["results"][0]["metrics"]["judge_completeness"] == 3.0
    assert report["results"][0]["metrics"]["judge_clarity"] == 4.0
    
    # Validate weighted overall
    expected_overall = (
        (4/4)*0.18 + (3/4)*0.22 + (2/4)*0.15 + 
        (4/4)*0.18 + (3/4)*0.12 + (3/4)*0.10 + (4/4)*0.05
    ) * 5.0
    assert report["results"][0]["metrics"]["judge_overall"] == pytest.approx(expected_overall)
```

### Priority 2 - Overlap Metrics Coverage

```python
def test_explanation_metrics_computes_all_overlap_scores() -> None:
    """Validate bigram_f1 and key_token_f1 are computed."""
    metrics = ExplanationMetrics().score(
        "Converts XML into a URL list using regex.",
        "Convert XML to URL List with patterns."
    )
    
    assert "token_f1" in metrics
    assert "key_token_f1" in metrics
    assert "bigram_f1" in metrics
    assert metrics["token_f1"] > 0.0
    assert metrics["key_token_f1"] > 0.0
    assert metrics["bigram_f1"] > 0.0
```

### Priority 3 - Error Tracking

```python
def test_code_explanation_evaluator_tracks_judge_errors() -> None:
    """Validate judge_error_count is incremented when judge fails."""
    case = ExplanationCase(...)
    prediction_provider = FakeProvider([
        json.dumps({"explanation": "Returns sum."})
    ])
    judge_provider = FakeProvider(['{"invalid json'])  # Malformed judge response
    
    report = CodeExplanationEvaluator(
        prediction_provider,
        judge=ExplanationJudge(judge_provider),
    ).evaluate([case])
    
    assert report["judge_error_count"] == 1
    assert report["results"][0]["judge_error"] is not None
```

### Priority 4 - Integration Test for Script

```python
def test_summarize_explainer_matrix_processes_all_metrics(tmp_path: Path) -> None:
    """End-to-end validation that script extracts all defined metrics."""
    # Create a mock report with all metrics
    report = tmp_path / "test_report.json"
    report.write_text(json.dumps({
        "results": [
            {
                "prediction": "Test explanation",
                "metrics": {
                    "judge_overall": 4.5,
                    "judge_purpose_accuracy": 4.0,
                    "judge_behavior_accuracy": 4.0,
                    "judge_api_contract": 3.0,
                    "judge_groundedness": 4.0,
                    "judge_specificity": 3.0,
                    "judge_completeness": 3.0,
                    "judge_clarity": 4.0,
                    "token_f1": 0.75,
                    "key_token_f1": 0.80,
                    "bigram_f1": 0.65,
                }
            }
        ],
        "error_count": 0,
        "judge_error_count": 0,
    }), encoding="utf-8")
    
    # Run script
    from scripts.summarize_explainer_matrix import summarize_report
    summary = summarize_report(report, bootstrap_samples=100)
    
    # Validate all metrics present
    assert "judge_overall" in summary
    assert "judge_purpose_accuracy" in summary
    assert "judge_behavior_accuracy" in summary
    assert "judge_api_contract" in summary
    assert "judge_groundedness" in summary
    assert "judge_specificity" in summary
    assert "judge_completeness" in summary
    assert "judge_clarity" in summary
    assert "token_f1" in summary
    assert "key_token_f1" in summary
    assert "bigram_f1" in summary
    assert summary["generation_errors"] == 0
    assert summary["judge_errors"] == 0
```

## Summary

**Total Metrics**: 14 (8 judge + 3 overlap + 3 error)
**Tested**: 6 metrics with reasonable coverage
**Partially Tested**: 2 metrics (judge_overall, token_f1 well covered)
**Untested**: 8 metrics (6 individual judge criteria + 2 overlap metrics)

**Coverage Rate**: ~43% (6/14 metrics with explicit tests)

**Risk Assessment**:
- **High Risk**: Individual judge criteria (6 metrics) have no validation
- **Medium Risk**: Overlap metrics partially tested
- **Low Risk**: Error tracking mostly covered

**Next Steps**:
1. Implement Priority 1 test (all judge criteria)
2. Implement Priority 2 test (overlap metrics)
3. Implement Priority 3 test (judge error tracking)
4. Consider Priority 4 integration test for end-to-end validation
