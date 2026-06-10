# H14 + Qwen3.5 4B — Full Report

## Overview

Goal: Test H14 (text-graph context, embeddinggemma-300m → switched to
Qwen3-Embedding-0.6B) with qwen4b as the answer/planning/reranking model,
keeping all retrieval infrastructure identical to the H14+Gemma26B run.

## Configuration

- Config: `configs/context-awareness/protogen-h14-qwen35-4b-text-graph.yml`
- Embedding: Qwen3-Embedding-0.6B (port 8001, same as H14+Gemma26B)
- Answer model: Qwen3.5-4B-OptiQ-4bit via mlx_lm server (port 8012)
- Strategy: `graph_file_rerank` with agentic queries (4 probes) + LLM rerank
- Dataset: `protogen_answer_cases_100.jsonl`, all 100 cases
- Judge: Gemini 3.1 Flash Lite (Vertex), strict answer prompt
- Workers: 1 (answer), 4 (query planning)

## Results

### Overall

| Metric | H14+Qwen4B | H14+Gemma26B | Δ |
|---|---|---|---|
| Cases | 100/100 (11 empty) | 100/100 | — |
| Total wall time | 2h10m | ~3h45m | −42% |
| Mean per-case | 79s | 135s | −41% |
| Generation errors | 11 (empty explanation) | 0 | −11 |

### Retrieval & Citation

| Metric | H14+Qwen4B | H14+Gemma26B | Δ |
|---|---|---|---|
| file_hit | 0.51 | 0.84 | −0.33 |
| candidate_file_hit@1 | 0.26 | 0.65 | −0.39 |
| candidate_file_hit@3 | 0.36 | 0.77 | −0.41 |
| context_file_hit | 0.48 | 0.82 | −0.34 |
| citation_path_valid_rate | 0.856 | 0.996 | −0.14 |
| citation_line_valid_rate | 0.847 | 0.995 | −0.15 |
| planned_queries | 3.76 | 3.79 | −0.03 |

### Lexical F1 (Token Overlap)

| Metric | H14+Qwen4B | H14+Gemma26B | Δ |
|---|---|---|---|
| token_f1 | 0.1242 | 0.1461 | −0.022 |
| key_token_f1 | 0.1198 | 0.1339 | −0.014 |
| bigram_f1 | 0.0467 | 0.0569 | −0.010 |

### Strict Judge Scores (0-4 each, max 24)

| Criterion | H14+Qwen4B | H14+Gemma26B | Δ |
|---|---|---|---|
| answer_correctness | 3.01 | 3.71 | −0.70 |
| evidence_grounding | 3.33 | 3.93 | −0.60 |
| coverage | 2.83 | 3.54 | −0.71 |
| citation_quality | 3.13 | 3.82 | −0.69 |
| specificity | 3.38 | 3.94 | −0.56 |
| hallucination_control | 3.45 | 4.00 | −0.55 |
| **★ Sum (max 24)** | **19.13** | **22.94** | **−3.81** |

### Component Latency Breakdown

| Component | H14+Qwen4B | H14+Gemma26B | Δ |
|---|---|---|---|
| Query planning | 11.1s | 8.8s | +2.3s |
| LLM rerank | 38.2s | 21.8s | +16.5s |
| Vector/lexical retrieval | 50.4s | 114.9s | −64.5s |
| Answer generation | 26.3s | 20.4s | +5.9s |
| **Mean total** | **78.6s** | **135.3s** | **−56.7s** |

### Comparison vs All Answer Candidates

| Candidate | ★Sum/24 | FileHit | CtxHit | CitVal | TokF1 | Lat(s) | Err |
|---|---|---|---|---|---|---|---|---|
| H14+Gemma26B | **22.94** | 0.84 | 0.82 | 0.996 | 0.1461 | 135 | 0 |
| H13+Gemma26B | 21.83 | 0.82 | 0.79 | 0.940 | 0.1462 | 242 | 4 |
| H14+Qwen4B | 19.13 | 0.51 | 0.48 | 0.856 | 0.1242 | 79 | 11 |
| H12B+GeminiFL | 17.73 | **0.89** | **0.89** | 0.987 | **0.1718** | **14** | 0 |
| H12A+GeminiFL | 16.55 | 0.86 | 0.86 | 0.957 | 0.1791 | 16 | 0 |

Sorted by ★Sum descending. H12A/B used Gemini Flash Lite as answer model
(not comparable to qwen4b or gemma26b for answer quality).

## Analysis

### Why H14+Qwen4B Underperforms H14+Gemma26B

1. **Query planning quality drops**: qwen4b generates weaker search queries
   (11.1s vs 8.8s but worse hits). The agentic planner doesn't explore
   effectively — candidate_file_hit@1 is 0.26 vs 0.65.

2. **LLM rerank is slower and worse**: qwen4b takes 38.2s to rerank vs 21.8s
   for gemma26b, and the reranked output has lower context_file_hit (0.48 vs
   0.82). qwen4b's reranking precision is worse.

3. **Empty explanations**: 11 cases produce empty predictions — qwen4b
   sometimes fails to generate any JSON output for the answer.

4. **Lower citation quality**: qwen4b cites the wrong line ranges or wrong
   files more often (0.856 vs 0.996).

5. **Judge-observed quality gap**: the strict judge penalizes qwen4b across
   all 6 criteria, especially coverage (−0.71) and correctness (−0.70).

### Positive Notes

- **Faster retrieval**: because qwen4b generates worse queries, the vector
  search runs faster (50.4s vs 114.9s) — but this is not a meaningful win.
- **Similar lexical F1**: token/key/bigram F1 are close to H14+Gemma26B
  (within 0.01-0.02), suggesting answer quality when retrieval works is
  comparable.
- **3x faster than H13** and faster than H14+Gemma26B on wall time.

## Decision

**Do not promote** H14+Qwen4B as the primary config. The retrieval quality
drop (−33% file_hit) is too severe. Keep as a lightweight fallback only
if latency is the binding constraint and quality can be sacrificed.

The optimal local setup remains: **H12B-style retrieval + qwen4b for
generation only** (no agentic queries, no qwen4b reranking).

## Files

- Config: `configs/context-awareness/protogen-h14-qwen35-4b-text-graph.yml`
- Raw report: `.code-diver/reports/protogen-h14-qwen4b-text-graph-100.json`
- Strict judge: `.code-diver/reports/strict-judge/h14-qwen4b-answer-strict.json`
