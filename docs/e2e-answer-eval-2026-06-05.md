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

The core product assumption is agent-first: the model should decide which search
queries to run. Deterministic hybrid/vector retrieval is a bounded tool the
agent calls, not the user-facing solution by itself.

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

To measure the agentic query-planning path:

```bash
uv run code-diver --root ../checked-out-repo --help-all evaluate-answers \
  --dataset path/to/answer-cases.jsonl \
  --cases 20 \
  --agentic-queries \
  --query-count 4 \
  --query-workers 4
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

1. In default mode, run the configured retrieval strategy once with the user
   question.
2. In `--agentic-queries` mode, ask the LLM to generate several targeted search
   probes, execute them in parallel, and merge/dedupe the file candidates.
3. Deduplicate top files.
4. Read bounded excerpts from each file.
5. Include the indexed file summary/manifest text beside the excerpt.
6. Ask the configured generation model for JSON:
   `answer`, `citations`, and `confidence`.

Default context width is strategy-aware: `4` files for `hybrid_rerank`, `8`
files for non-reranked search. The Qibo mini-matrix below showed that rerank
already moves the useful file bundle high enough that wider context mostly adds
noise, while non-reranked `hybrid` needs a wider context window to avoid dropping
evidence.

This is Branch A-lite. It does not yet let the answer model freely call
outline/symbol/rg/read tools inside the final answer step. `--agentic-queries`
adds the first agentic decision point: LLM-generated search probes before
retrieval. It still does not yet build the Branch B ephemeral syntax-aware index
over candidate files. Those are the next controlled comparisons.

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
| `planned_query_count` | Number of search probes used for this case. |
| `planning_duration_ms` | Time spent asking the model to plan search probes. |
| `citation_path_valid_rate` | Fraction of answer citations pointing to files in the retrieved context. |
| `citation_line_valid_rate` | Fraction of answer citations whose line range overlaps the retrieved excerpt. |

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
2. Compare single-query retrieval against `--agentic-queries` on Qibo and larger
   SWE-QA-Pro slices.
3. Compare Branch A full agentic file inspection against the current bounded
   context reader.
4. Compare Branch B ephemeral syntax-aware candidate-file indexing.
5. Run the same answer/judge setup with Gemma 4 E4B, Qwen3.5, and Gemini Lite.

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

## Public SWE-QA-Pro Mini-Run

Public dataset:

- Dataset: `TIGER-Lab/SWE-QA-Pro-Bench`
- Repository: `qiboteam/qibo`
- Commit: `2f98679c4a738d5a59de17eccd4712659d52a461`
- Local checkout: `/tmp/code-diver-qibo`
- Cases: first 2 rows for that repo

The first attempt exposed a real runtime bug: the active local Qwen3 embedding
profile allowed `max_input_chars=900`, but the served model is started with
`--max-model-len 512`. One file manifest crossed the token limit and vLLM
returned HTTP 400. Active Qwen profile/config caps were lowered to `400`.

Commands:

```bash
uv run code-diver --root /tmp/code-diver-qibo --help-all evaluate-answers \
  --dataset /tmp/code-diver-swe-qibo-3.jsonl \
  --cases 2 \
  --limit 10 \
  --context-files 8 \
  --context-lines 180 \
  --reindex \
  --output /tmp/code-diver-e2e-qibo-2.json

uv run code-diver --root /tmp/code-diver-qibo --help-all evaluate-answers \
  --dataset /tmp/code-diver-swe-qibo-3.jsonl \
  --cases 2 \
  --limit 10 \
  --context-files 8 \
  --context-lines 180 \
  --judge \
  --judge-prompt prompts/code-answer-judge.md \
  --judge-model gemini-3.1-flash-lite \
  --output /tmp/code-diver-e2e-qibo-2-judge.json
```

Index summary:

| Metric | Value |
| --- | ---: |
| files | `281` |
| H6.1 records | `562` |
| content MB | `0.57` |
| embedding batches | `5` |
| indexing time | `~5s` |

No-judge result:

| Metric | Value |
| --- | ---: |
| `cases` | `2` |
| `file_hit` | `1.000` |
| `file_recall` | `0.750` |
| `candidate_file_hit@1` | `1.000` |
| `candidate_file_hit@5` | `1.000` |
| `context_file_recall` | `0.750` |
| `token_f1` | `0.400` |
| `key_token_f1` | `0.355` |
| `bigram_f1` | `0.158` |
| `retrieval_duration_ms` | `1428` |
| `context_duration_ms` | `5` |
| `generation_duration_ms` | `1748` |
| `answer_duration_ms_mean` | `3183` |

Judge result:

| Metric | Value |
| --- | ---: |
| `cases` | `2` |
| `file_recall` | `0.750` |
| `context_file_recall` | `0.750` |
| `judge_answer_correctness` | `3.500` |
| `judge_evidence_grounding` | `4.000` |
| `judge_coverage` | `2.500` |
| `judge_citation_quality` | `3.500` |
| `judge_specificity` | `3.500` |
| `judge_hallucination_control` | `4.000` |
| `judge_overall` | `4.375` |
| `retrieval_duration_ms` | `1644` |
| `generation_duration_ms` | `1817` |
| `judge_duration_ms` | `17856` |
| `answer_duration_ms_mean` | `21325` |

Per-case notes:

| Case | Expected files | Context recall | Judge overall | Observed failure |
| --- | --- | ---: | ---: | --- |
| `swe-qa-pro-00001` | `src/qibo/models/variational.py` | `1.000` | `3.938` | Judge flagged inaccurate line-number citations and incomplete specialized-method detail. |
| `swe-qa-pro-00002` | `src/qibo/states.py`, `src/qibo/backends/numpy.py` | `0.500` | `4.813` | Context missed `src/qibo/backends/numpy.py`; answer remained mostly correct from available evidence. |

This mini-run is too small for a quality claim, but it validates the public
benchmark path and shows the next concrete targets:

1. Citation line accuracy needs stricter extraction or post-validation.
2. Multi-file workflow questions need better bundle recall, not just first-file
   hit.
3. Judge is benchmark-only overhead; it adds ~18s/case here and should not be
   part of interactive latency.
4. Repeated runs can change top-rank order even with temperature 0, so larger
   E2E comparisons should run with saved reports and confidence intervals.

## Qibo Context/Rerank Matrix

Same 3-case Qibo slice, no judge, `limit=12`, `context-lines=180`:

| Strategy | Context files | File recall | Context recall | Context precision | Hit@1 | Hit@3 | Hit@5 | Token F1 | Bigram F1 | Retrieval ms | Total ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hybrid` | 4 | `0.611` | `0.333` | `0.083` | `0.333` | `0.333` | `0.333` | `0.275` | `0.065` | `1164` | `2786` |
| `hybrid` | 8 | `0.611` | `0.611` | `0.125` | `0.333` | `0.333` | `0.333` | `0.368` | `0.135` | `321` | `2134` |
| `hybrid` | 12 | `0.611` | `0.611` | `0.094` | `0.333` | `0.333` | `0.333` | `0.335` | `0.145` | `319` | `1994` |
| `hybrid_rerank` | 4 | `0.722` | `0.722` | `0.333` | `0.667` | `1.000` | `1.000` | `0.365` | `0.135` | `1440` | `3205` |
| `hybrid_rerank` | 8 | `0.722` | `0.722` | `0.167` | `0.667` | `1.000` | `1.000` | `0.361` | `0.152` | `1441` | `3181` |
| `hybrid_rerank` | 12 | `0.722` | `0.722` | `0.131` | `0.667` | `1.000` | `1.000` | `0.385` | `0.157` | `1530` | `3336` |

Interpretation:

- Rerank improves file bundle recall on this slice: `0.611 -> 0.722`.
- Rerank also moves relevant files into the top 3/5, so `context-files=4` is
  enough and gives the highest context precision.
- Without rerank, `context-files=4` drops evidence; `8` recovers all candidate
  recall available in the top 12.
- `context-files=12` adds noise without improving recall on this slice.

Follow-up citation-validation run:

| Metric | Value |
| --- | ---: |
| `citation_count` | `2.500` |
| `citation_path_valid_rate` | `1.000` |
| `citation_line_valid_rate` | `1.000` |
| `judge_citation_quality` | `3.500` |
| `judge_overall` | `4.188` |
| `answer_duration_ms_mean` | `5441` |

The deterministic citation checks passed: cited files were in context and cited
line ranges overlapped the retrieved excerpts. The judge still rated citation
quality below perfect because one answer cited an existing range that was not the
best evidence for the full specialized-method claim. This separates two classes
of citation failure:

- **Malformed citation**: path/range not present in retrieved context. The new
  deterministic metrics catch this cheaply.
- **Weak evidence citation**: path/range exists but does not fully support the
  claim. This still needs judge scoring or a future claim-to-evidence verifier.

## Agentic Query-Planning Smoke

Same 3-case Qibo slice, same `hybrid_rerank` strategy, no judge,
`limit=12`, `context-files=4`, `context-lines=180`.

The comparison isolates the first agentic decision point:

- single-query mode sends the user's original question directly to H6.1;
- `--agentic-queries` asks the answer model to generate up to four search probes,
  runs those retrieval calls in parallel, merges candidates, then uses the same
  context reader and answer generator.

Commands:

```bash
uv run code-diver --root /tmp/code-diver-qibo --help-all evaluate-answers \
  --dataset /tmp/code-diver-swe-qibo-3.jsonl \
  --cases 3 \
  --limit 12 \
  --context-lines 180 \
  --output /tmp/code-diver-e2e-qibo-3-single-after-agentic.json

uv run code-diver --root /tmp/code-diver-qibo --help-all evaluate-answers \
  --dataset /tmp/code-diver-swe-qibo-3.jsonl \
  --cases 3 \
  --limit 12 \
  --context-lines 180 \
  --agentic-queries \
  --query-count 4 \
  --query-workers 4 \
  --output /tmp/code-diver-e2e-qibo-3-agentic-queries.json
```

| Mode | Planned queries | File recall | Context recall | Context precision | Hit@1 | Hit@3 | Hit@5 | Token F1 | Bigram F1 | Planning ms | Retrieval ms | Total ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Single query | `1.000` | `0.722` | `0.722` | `0.333` | `0.667` | `1.000` | `1.000` | `0.365` | `0.135` | `0` | `2535` | `4227` |
| LLM multi-query | `4.000` | `0.722` | `0.722` | `0.333` | `0.667` | `0.667` | `1.000` | `0.366` | `0.144` | `1380` | `3629` | `5357` |

Interpretation:

- This smoke does **not** prove agentic query planning is useful yet.
- Recall stayed flat, `Hit@3` got worse, and latency increased by ~1.1s/case.
- The product direction is still agent-first, but the current planner is only
  the first controlled slice: LLM-generated probes need better prompts, better
  merge/scoring, or a cheaper base retrieval mode before scaling.
- The next controlled test should compare:
  1. multi-query planning over fast non-reranked `hybrid`, followed by one final
     LLM rerank over the merged pool;
  2. query diversity constraints so generated probes do not collapse onto the
     same lexical intent;
  3. full Branch A inspection where the model can call outline/symbol/rg/read on
     candidate files before answering.
