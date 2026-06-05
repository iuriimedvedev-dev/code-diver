# Model Axis Current State - 2026-06-05

## Product Pipeline

The product is a code-answering agent, not a standalone file searcher. The
intended runtime is:

```text
agent receives user question
-> deterministic hybrid file search over calibrated H6.1 indexes
-> LLM reranks the candidate files
-> answer agent reads file outlines, symbols, rg/grep hits, and source ranges
-> answer agent explains the code and answers the user's question with evidence
```

Older notes use `static` to mean "deterministic locator only." That is only the
candidate-generation stage, not the whole product.

The branch we still need to compare inside the answer agent is:

```text
candidate files
-> A: agent uses bounded outline/symbol/rg/grep/read tools directly
-> B: build/use an ephemeral syntax-aware code index inside those files, then rerank/read
-> final answer
```

## Three Separate Model Variables

| Variable | Job | Current best evidence | Current decision |
| --- | --- | --- | --- |
| Embedding model | Build/query the H6.1 file metadata locator. | EmbeddingGemma-300M H6.1 is the current best same-stack local default. Earlier Qwen3 0.6B/4B tests were weaker after rerank on Protogen; Qwen 4B improved raw candidate generation but did not improve the best Gemini-reranked result. | Keep EmbeddingGemma-300M as default, continue controlled A/B against Qwen 0.6B/4B and code-specialized embeddings. |
| Reranker model | Reorder a fixed candidate set from H6.1 before code reading. | Gemini 3.1 Flash Lite is the best measured reranker on the current 100-case same-index slice. | Use Gemini Lite for quality mode; keep local rerankers as offline/local-only candidates. |
| Answer-agent model | Choose tool calls over the reranked files, read/grep/source-inspect, and answer the user's code question. | We have stage evidence that Gemma E4B is a strong local explainer. The first E2E smoke found a serving/config bug: local Gemma structured tasks must use `response_format: json_schema`, not the old `response_format: false` workaround. | Re-run local Gemma answer-agent evals with corrected structured output before making final local-model decisions. |

The first E2E benchmark runner is now implemented as `evaluate-answers`. It
measures retrieval/rerank, bounded context reads, final answer generation, and
optional AI-judge scoring. Current scope is deterministic bounded context over a
local checkout; the next comparison is full Branch A agentic inspection versus
Branch B ephemeral candidate-file indexing.

## Search-Planning Slice Result

This is not the final product metric. It is a 100-case CodeSearchNet slice that
measures what happens when an LLM is allowed to operate in the search-planning
part of the pipeline before the final explanation step:

```text
question -> H6.1 search tool -> model/tool loop -> optional rerank -> ranked files
```

| Setup | Cases | Hit@1 | Hit@5 | Hit@10 | Precision@10 | nDCG@10 | Mean ms | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| H6.1 deterministic locator | 100 | 0.820 | 0.970 | 0.970 | 0.147 | 0.900 | 858 | Best broad candidate generation. |
| H6.1 + Gemini 3.1 Flash Lite search-planning/rerank | 100 | 0.740 | 0.860 | 0.860 | 0.277 | 0.813 | 10,660 | Better precision, worse recall. Candidate for gated precision mode. |
| H6.1 + Gemma 4 E2B local search-planning/rerank | 100 | 0.510 | 0.640 | 0.700 | 0.070 | 0.596 | 11,501 | Fully local and stable, but not good enough for search ranking. |

Interpretation:

- H6.1 locator is currently the best broad candidate generator.
- Gemini Lite can narrow results and improve Precision@10, but as an unrestricted
  search-planning loop it drops too many correct files.
- Gemma E2B should not run the search-planning loop in the current prompt/tool
  contract.
- These numbers do not answer whether the final answer-agent can explain code
  well after receiving the right files.

## Explanation / Judge Result

This is a separate axis. It does not measure whether retrieval found the right
file. It measures whether a model can explain a known code snippet against a
reference answer, with an AI judge questionnaire.

| Explainer | Judge | Cases | Judge overall | Purpose | Behavior | Groundedness | Completeness | Clarity | Mean ms/case | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Gemma 4 E2B | Gemma 4 E4B | 100 | 1.283 | 1.08 | 1.05 | 1.07 | 1.00 | 1.08 | 2,896 | Too weak as explainer. |
| Gemma 4 E4B | Gemma 4 E4B | 100 | 4.252 | 3.56 | 3.51 | 3.51 | 3.36 | 3.55 | 6,296 | Strong local explainer candidate. |
| Gemma 4 E2B | Qwen3.5 9B | 100 | 1.198 | 0.96 | 0.96 | 0.96 | 0.96 | 0.96 | 3,490 | Cross-family judge agrees E2B is weak. |
| Gemma 4 E4B | Qwen3.5 9B | 100 | 4.430 | 3.54 | 3.54 | 3.53 | 3.55 | 3.56 | 9,500 | Cross-family judge agrees E4B is strong. |

Current interpretation:

- Gemma 4 E4B is currently the best local explainer we have measured.
- Gemma 4 E2B is usable for narrow structured rerank, but not for explanation.
- Qwen3.5 9B is useful as a cross-family judge, but its latency makes it a poor
  default reranker in the current prompt budget.
- This still is not the full answer-agent eval because the code snippet is given
  to the model instead of discovered through H6.1 search + rerank + read/grep.

## Local Gemma Structured-Output Fix

The local Gemma answer/search experiments hit a real serving-contract bug. The
MLX Gemma server applies the checkpoint chat template itself, and its structured
output path expects OpenAI-compatible `response_format.type=json_schema`. Our
older configs disabled response format after `json_object` failures, so local
Gemma was often asked to produce JSON by prompt only.

Fixes now landed:

- preserve `response_format: json_schema` in config loading;
- send JSON Schema payloads from the OpenAI-compatible provider;
- keep `extra_body.enable_thinking=false` for structured JSON tasks;
- preserve retrieval/context metrics when answer JSON parsing fails;
- include `path_role` in LLM-rerank candidates;
- tell rerankers to prefer implementation owner files over tests/examples/docs
  unless the query explicitly asks for supporting files.

Tiny Qibo 3-case smoke after the fix:

| Setup | File recall | File MRR | Candidate Hit@1 | Candidate Hit@5 | Context recall | Token F1 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini Lite H7 baseline | 0.722 | 1.000 | 1.000 | 1.000 | 0.722 | 0.434 | 4,694 |
| Gemma E2B before path-role fix | 0.611 | 0.161 | 0.000 | 0.667 | 0.000 | 0.171 | 9,130 |
| Gemma E2B json_schema + path_role | 0.611 | 0.694 | 0.667 | 0.667 | 0.444 | 0.208 | 21,659 |
| Gemma E4B before path-role fix | 0.611 | 0.426 | 0.333 | 0.333 | 0.333 | 0.308 | 26,868 |
| Gemma E4B json_schema + path_role | 0.611 | 0.704 | 0.667 | 0.667 | 0.444 | 0.314 | 26,621 |

Interpretation: the old local Gemma runs are directional only. The corrected
format materially improves head ranking, but Gemini Lite remains better and much
faster on this smoke. See `docs/gemma-4-local-template-fix-2026-06-05.md`.

## Rerank-Only Result

This isolates the reranker role. The candidate generator is fixed:

```text
H6.1 EmbeddingGemma locator -> top 30 structured candidates -> one-shot LLM rerank
```

The model does not plan new searches and does not read files. It only reorders the
same H6.1 candidate set.

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | P95 ms | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| H6.1 deterministic locator | 100 | 0.820 | 0.930 | 0.970 | 0.970 | 0.970 | 0.147 | 0.876 | 0.900 | 858 | 863 | Baseline candidate order. |
| H6.1 + Gemma 4 E2B rerank-only | 100 | 0.800 | 0.930 | 0.970 | 0.970 | 0.970 | 0.147 | 0.870 | 0.895 | 3,444 | 3,958 | Stable local reranker, but slightly worse than baseline. |
| H6.1 + Gemma 4 E4B rerank-only | 100 | 0.830 | 0.930 | 0.970 | 0.970 | 0.970 | 0.147 | 0.883 | 0.905 | 7,927 | 9,035 | Small quality gain, high local latency. |
| H6.1 + Gemini 3.1 Flash Lite rerank-only | 100 | 0.900 | 0.980 | 0.990 | 0.990 | 0.990 | 0.153 | 0.941 | 0.953 | 2,530 | 3,985 | Best observed reranker on this controlled slice. |
| H6.1 + Qwen3.5 9B rerank-only | 100 | 0.840 | 0.950 | 0.960 | 0.970 | 0.970 | 0.151 | 0.896 | 0.915 | 19,125 | 21,872 | Best local quality after E4B, but too slow for default reranking. |

Current interpretation:

- Reranking **is** an LLM-shaped task, but the role contract must be tight.
- The 100-case rerank-only run sends roughly 1M input tokens through the reranker
  because each case carries 30 structured candidates with previews. Prompt budget
  is therefore a first-class tuning knob, not an implementation detail.
- Gemma 4 E2B failed as an unrestricted agent, but is acceptable as a bounded
  reranker. It still does not improve H6.1.
- Gemma 4 E4B gives a small rerank-only quality lift, but costs too much latency
  for a default interactive reranker.
- Qwen3.5 9B improves over the H6.1 baseline on Hit@1/MRR/nDCG, but its current
  prompt/candidate budget makes it impractical as an always-on local reranker.
- Gemini 3.1 Flash Lite currently gives the best quality/latency tradeoff for the
  reranker role.
- Current default recommendation: H6.1 EmbeddingGemma locator plus Gemini 3.1
  Flash Lite reranker. For local-only mode, prefer Gemma 4 E2B when latency is
  strict and Qwen3.5 9B only for slower high-quality/offline runs.

Trace token/cost notes:

| Reranker | Rerank responses | Input tokens | Output tokens | Estimated API cost |
| --- | ---: | ---: | ---: | ---: |
| Gemma 4 E2B local | 100 | 1,077,421 | 4,958 | local runtime, no API bill |
| Gemma 4 E4B local | 100 | 1,077,421 | 4,223 | local runtime, no API bill |
| Gemini 3.1 Flash Lite | 100 | 1,075,620 | 7,214 | ~$0.28 |
| Qwen3.5 9B local | 100 | 966,718 | 14,935 | local runtime, no API bill |

## Local Gemma 4 Rerank Update - 2026-06-06

A same-index local-only rerank matrix was run on 10/100/200 CodeSearchNet cases
after fixing local Gemma structured output. See
`docs/gemma4-local-rerank-matrix-2026-06-06.md`.

The 200-case result:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Mean ms | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| H6.1 static | 200 | 0.800 | 0.935 | 0.970 | 0.975 | 0.8695 | 0.8960 | 872 | Default broad candidate order. |
| H6.1 + Gemma 4 E2B precision | 200 | 0.780 | 0.945 | 0.970 | 0.975 | 0.8623 | 0.8909 | 3619 | Reject as always-on reranker. |
| H6.1 + Gemma 4 E2B base-prior | 200 | 0.795 | 0.935 | 0.965 | 0.975 | 0.8671 | 0.8943 | 3946 | Reject as always-on reranker. |
| H6.1 + Gemma 4 E4B precision | 200 | 0.805 | 0.935 | 0.970 | 0.975 | 0.8729 | 0.8985 | 8866 | Marginal quality lift, high latency. |
| H6.1 + Gemma 4 E4B base-prior | 200 | 0.810 | 0.940 | 0.970 | 0.975 | 0.8758 | 0.9007 | 8819 | Best local reranker so far, but gate it. |

Interpretation: Gemma 4 E4B base-prior is the best local reranker measured so
far, but the gain over static H6.1 is small (`+0.010` Hit@1, `+0.0047` nDCG)
for roughly `10x` mean latency. It should be used for hard/ambiguous queries or
offline quality mode, not as the default for every interactive query.

## What We Still Need To Test

### 1. Embedding Axis

Run identical H6.1 locator configs with:

- `google/embeddinggemma-300m`
- Qwen3-Embedding 0.6B
- Qwen3-Embedding 4B
- any current code-specific local embedding candidate that fits the runtime

Metrics:

- index build time;
- index size;
- Hit@1/3/5/10;
- Recall@10;
- Precision@10;
- MRR/nDCG;
- mean/p95 query latency.

### 2. Reranker Axis

Do **not** give the model full search control for this test. Freeze H6.1 top-N
candidates and run one-shot rerank:

```text
query + structured top-N candidates -> reranked file list
```

Candidates:

- Gemini 3.1 Flash Lite;
- Gemma 4 E2B;
- Gemma 4 E4B;
- Qwen3.5 local;
- Qwen3-Reranker cross-encoder if a real rerank endpoint is available.

This isolates whether a local model can rank files. The latest E2B agent result
does not isolate that because it mixes query planning, tool selection, and rerank.

### 3. Answer-Agent Axis

This is a separate product metric:

```text
question -> H6.1 hybrid search -> LLM rerank -> read/grep/source inspection -> final answer
```

Retrieval Hit@K cannot score this. We need:

- answer groundedness;
- cited file/line correctness;
- completeness;
- clarity;
- whether the answer read the right files;
- AI-judge rubric with cross-family judge control.

Current local explainer evidence points to Gemma E4B over Gemma E2B. Qwen3.5 9B
is useful as cross-family judge, not yet proven as the best explainer.

The next answer-agent experiment must compare:

- **Branch A:** reranked files -> bounded outline/symbol/rg/grep/read -> answer;
- **Branch B:** reranked files -> ephemeral syntax-aware code index -> code-level
  retrieval/rerank -> read -> answer.
