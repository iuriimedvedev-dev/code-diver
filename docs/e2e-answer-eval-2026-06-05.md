# E2E Answer Evaluation

Updated: 2026-06-05.

## Purpose

Retrieval metrics tell us whether Code Diver found the right files. Code
explanation metrics tell us whether a model can explain a snippet that is already
known. The product needs both:

```text
question
-> H6.1 hybrid file locator
-> LLM rerank
-> bounded file context reads
-> final answer with file/line evidence
-> optional AI judge
```

`evaluate-answers` is the first benchmark lane for that full path.

## Command

The command is advanced because the public assignment surface remains
`index`, `search`, and `evaluate`.

```bash
uv run code-diver --root ../checked-out-repo --help-all evaluate-answers \
  --benchmark swe-qa-pro \
  --repo owner/name \
  --cases 20 \
  --yes \
  --judge \
  --judge-prompt prompts/code-answer-judge.md \
  --judge-model gemini-3.1-flash-lite
```

The runner writes:

- full report: `.code-diver/reports/code-answer-e2e-eval.json`
- partial report while running:
  `.code-diver/reports/code-answer-e2e-eval.json.partial`

If `--benchmark swe-qa-pro` is used and the local JSONL does not exist, the CLI
asks before preparing it unless `--yes` is passed. Preparation uses
`TIGER-Lab/SWE-QA-Pro-Bench` test rows and writes Code Diver answer cases under
`.code-diver/benchmarks/swe-qa-pro/`.

## Current Scope

The first implementation evaluates a local repository root. For SWE-QA-Pro, that
means `--root` must point to a checkout of the requested `--repo` at the relevant
commit. Automatic clone/checkout/index caching is intentionally not hidden inside
the first runner because it changes benchmark cost and latency semantics.

The current answer context is deterministic:

1. Run the configured retrieval strategy.
2. Deduplicate top files.
3. Read bounded excerpts from each file.
4. Include the indexed file summary/manifest text beside the excerpt.
5. Ask the configured generation model for JSON:
   `answer`, `citations`, and `confidence`.

This is Branch A-lite. It does not yet let the answer model freely call
outline/symbol/rg/read tools inside the final answer step, and it does not yet
build the Branch B ephemeral syntax-aware index over candidate files. Those are
the next controlled comparisons.

## Metrics

The report includes retrieval-derived file metrics when the dataset has expected
paths:

| Metric | Meaning |
| --- | --- |
| `file_hit` | At least one expected file appears in retrieved candidates. |
| `file_recall` | Fraction of expected files covered by retrieved candidates. |
| `file_precision` | Fraction of retrieved files that are expected files. |
| `file_mrr` | Reciprocal rank of the first expected file. |
| `candidate_file_hit@1/3/5/K` | Whether the top N retrieved files contain at least one expected file. |
| `candidate_file_recall@1/3/5/K` | Expected file coverage in the top N retrieved files. |
| `context_file_hit` | Whether at least one expected file survives into the answer context. |
| `context_file_recall` | Expected file coverage in the files actually read into context. |
| `context_file_precision` | Fraction of context files that are expected files. |

It also includes cheap answer/reference text overlap:

| Metric | Meaning |
| --- | --- |
| `token_*` | Unigram overlap with the reference answer. |
| `key_token_*` | Stop-word-filtered unigram overlap. |
| `bigram_*` | Two-token phrase overlap. |

With `--judge`, the editable judge prompt
[prompts/code-answer-judge.md](../prompts/code-answer-judge.md) adds a structured
questionnaire:

| Metric | Scale | Meaning |
| --- | ---: | --- |
| `judge_answer_correctness` | 0-4 | Directly answers the question correctly. |
| `judge_evidence_grounding` | 0-4 | Important claims are supported by context/reference. |
| `judge_coverage` | 0-4 | Covers required files, methods, behaviors, and relationships. |
| `judge_citation_quality` | 0-4 | File/line citations are useful and consistent with evidence. |
| `judge_specificity` | 0-4 | Uses concrete code names and responsibilities. |
| `judge_hallucination_control` | 0-4 | Avoids invented APIs, files, line numbers, and architecture. |
| `judge_overall` | 0-5 | Weighted final score computed deterministically from the questionnaire. |

## What This Fixes

Earlier reports could only say "we found likely files" or "Gemma E4B can explain
a known snippet." They could not answer whether the full product gives a useful
answer to a repository question. This lane separates the stages but keeps them
in one reproducible report.

## Next Experiments

1. Add repo checkout/cache preparation for SWE-QA-Pro by `repo@commit_id`.
2. Compare Branch A full agentic file inspection against the current deterministic
   bounded-context reader.
3. Compare Branch B ephemeral syntax-aware candidate-file indexing.
4. Run the same answer/judge setup with Gemma 4 E4B, Qwen3.5, and Gemini Lite.
5. Store per-stage cost and latency separately: retrieval, context read, answer,
   judge.

## Initial Local Smoke

Command:

```bash
uv run code-diver --root . --help-all evaluate-answers \
  --dataset /tmp/code-diver-answer-smoke.jsonl \
  --cases 1 \
  --limit 8 \
  --context-files 4 \
  --context-lines 120 \
  --output /tmp/code-diver-e2e-smoke.json
```

Result:

| Metric | Value |
| --- | ---: |
| `cases` | `1` |
| `file_hit` | `1.000` |
| `file_recall` | `0.333` |
| `file_precision` | `0.200` |
| `file_mrr` | `0.500` |
| `candidate_file_hit@3` | `1.000` |
| `candidate_file_hit@5` | `1.000` |
| `context_file_hit` | `1.000` |
| `context_file_recall` | `0.333` |
| `token_f1` | `0.286` |
| `key_token_f1` | `0.259` |
| `bigram_f1` | `0.067` |
| `retrieval_duration_ms` | `2290` |
| `context_duration_ms` | `1` |
| `generation_duration_ms` | `2230` |
| `answer_duration_ms_mean` | `4522` |
| answer model tokens | `10090` |

Expected files were:

- `src/code_diver/cli.py`
- `src/code_diver/answering/answer_evaluator.py`
- `src/code_diver/answering/answer_context_builder.py`

The retrieved/context bundle covered `answer_evaluator.py` but missed `cli.py`
and `answer_context_builder.py`; it also pulled the new docs and tests. The final
Gemini Lite answer was coherent, but the evidence bundle was incomplete. This is
the first concrete proof that answer quality cannot be inferred from a single
retrieved file hit: E2E needs bundle recall, citation quality, and judge metrics.

## First Stage-Metrics Ablation

Same one-case local smoke, same index, same answer model:

| Setup | Context files | Candidate hit@3 | Candidate hit@5 | Context hit | Context recall | Retrieval ms | Generation ms | Total ms | Judge overall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid_rerank` | 4 | `1.000` | `1.000` | `1.000` | `0.333` | `2290` | `2230` | `4522` | not run |
| `hybrid` | 4 | `0.000` | `1.000` | `0.000` | `0.000` | `1159` | `2687` | `3849` | not run |
| `hybrid_rerank` + judge | 4 | `1.000` | `1.000` | `1.000` | `0.333` | `2122` | `2465` | `6572` | `4.813` |

Interpretation:

- Plain `hybrid` had the right file by rank 5, but `context-files=4` dropped it.
- `hybrid_rerank` roughly doubled retrieval latency on this smoke, but moved one
  expected file into the answer context.
- Local file reading is not the bottleneck here: context assembly was ~1-2 ms.
- The next optimization should test a cheaper gate: run fast `hybrid`, include a
  slightly wider deduped context, or rerank only when the top-file confidence is
  weak.
