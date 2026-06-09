# Retrieval Metrics

This project measures retrieval quality before answer generation. The goal is to know whether the search layer returns the right files or symbols inside a small top-k context budget.

## Dataset Case Shape

Each JSONL case has:

- `id`: stable case id.
- `query`: natural-language retrieval query.
- `expected`: list of expected item ids or path prefixes.

An item is counted as relevant when its indexed id matches an expected id exactly, or when its path starts with an expected path prefix.

## Metrics

| Metric | Meaning | Good value | What it tells us |
| --- | --- | ---: | --- |
| `cases` | Number of evaluation cases included in the run. | Higher is better for confidence. | Small values make results noisy. Current protogen eval has 10 cases, so treat differences below ~0.1 carefully. |
| `hit_rate@10` | Fraction of cases where at least one relevant item appears in the top 10. | `1.0` | Measures candidate recall. Useful for diagnosing whether reranking even has a chance, but too loose for the final user-visible result. |
| `mrr@10` | Mean reciprocal rank of the first relevant item in top 10. Rank 1 = `1.0`, rank 2 = `0.5`, rank 10 = `0.1`, no hit = `0`. | `1.0` | Measures ranking quality. High hit rate with low MRR means relevant files are present but buried. |
| `precision@10` | Relevant retrieved items divided by retrieved items, averaged across cases. | `1.0` | Measures result cleanliness. Low precision means the model will waste context tokens on irrelevant snippets. |
| `recall@10` | Expected relevant targets found in top 10, averaged across cases. | `1.0` | Measures coverage when a case has multiple expected files. |
| `hit_rate@1` | Fraction of cases where the first retrieved item is relevant. | `1.0` | Strong proxy for whether the first answer citation will be correct. |
| `hit_rate@3` | Fraction of cases where any of the first three retrieved items is relevant. | `1.0` | Primary short-list quality metric. If this is weak, the searcher will waste verification reads. |
| `hit_rate@5` | Fraction of cases where any of the first five retrieved items is relevant. | `1.0` | Main practical context-budget metric for the AI searcher. This is a better target than top-10. |
| `file_hit_rate@10` | Fraction of cases where any deduplicated retrieved file matches expected files. | `1.0` | Removes repeated chunk effects from `hit_rate@10`. |
| `file_mrr@10` | MRR over deduplicated file paths instead of chunks/symbols. | `1.0` | Measures whether the right file appears early, regardless of chunk multiplicity. |
| `file_precision@R` | Precision over the first R deduplicated files, where R is the number of expected targets. | `1.0` | Main cleanliness metric for code search; avoids penalizing single-file answers for not filling 10 slots. |
| `file_recall@10` | Expected file targets covered by deduplicated top-10 files. | `1.0` | More honest coverage than chunk-level recall when many chunks from one file repeat. |
| `ndcg@10` | Normalized discounted cumulative gain over deduplicated file results. | `1.0` | Rewards ranking all expected files early and penalizes burying them. |
| `map@10` | Mean average precision over deduplicated file results. | `1.0` | Measures file-level ranking quality across all expected targets. |
| `duration_ms` | Wall-clock evaluation time for that strategy over all cases. | Lower is better. | Measures retrieval latency in the current implementation and storage backend. Do not compare across machines without noting hardware/backend. |
| `search_duration_ms_total` | Sum of all per-query retrieval calls inside an evaluation. | Lower is better. | Isolates retrieval time from indexing and orchestration time. |
| `search_duration_ms_mean` | Average retrieval latency per dataset query. | Lower is better. | Useful for comparing vector, recursive, and graph strategies under the same index. |
| `search_duration_ms_p95` | Approximate p95 retrieval latency per dataset query. | Lower is better. | Shows tail latency; important for interactive agent use. |
| `indexing_duration_ms` | Wall-clock time spent by the AI orchestrator to inspect and build a selected index. | Lower is better. | Includes model latency and tool execution. |
| `evaluation_duration_ms` | Wall-clock time spent evaluating the completed index. | Lower is better. | Includes embedding queries and vector retrieval. |
| `indexed_items` | Number of vector points stored for a hypothesis. | Depends. | More items can improve recall but increases storage, search fanout, and context noise. |
| `index_items` | Number of vector points in the active store during `experiment`. | Depends. | Lets search-only sweeps report the size of the index they used. |
| `index_vector_dimensions` | Dense vector dimensionality from store metadata. | Depends. | Needed to estimate raw vector memory. |
| `index_vector_bytes_estimate` / `index_vector_mb_estimate` | `index_items * dimensions * 4`, assuming float32 vectors. | Lower is better at equal quality. | Approximate raw dense vector footprint before Qdrant/HNSW/payload overhead. |
| `graph_artifact_bytes` / `graph_artifact_mb` | Size of the graph JSON artifact. | Lower is better at equal quality. | Important because the graph currently stores item payloads too; compact item content matters. |
| `index_artifact_bytes` / `index_artifact_mb` | Size of the JSON index artifact when JSON storage is used. | Lower is better at equal quality. | Mostly useful for JSON-store experiments. |
| `orchestrator_usage.total_tokens` | Total input and output tokens reported by the provider, or estimated from prompt/response size when the provider omits usage. | Lower is better at equal quality. | Primary token budget metric for AI-orchestrated search/indexing. |
| `orchestrator_usage.input_tokens` | Prompt, tool result, and context tokens sent to the model. | Lower is better. | High values usually mean tool outputs are too large or too many turns are used. |
| `orchestrator_usage.output_tokens` | Tokens generated by the model. | Lower is better at equal quality. | Measures orchestration verbosity and JSON planning overhead. |
| `orchestrator_usage.total_cost` | Estimated provider cost from token counts and configured model class. | Lower is better at equal quality. | Main dollar-cost metric for orchestrator comparisons. |
| `orchestrator_usage.tool_calls` | Number of direct tool calls executed by the orchestrator. | Depends. | Too few means poor inspection; too many means slow and token-heavy runs. |
| `llm_rerank_response.total_tokens` | Provider-reported token use for one bounded rerank call. | Lower is better at equal quality. | Used by `hybrid_rerank`; unlike `orchestrator_usage`, this is logged per retrieval query in the trace. |
| `llm_rerank_response.estimated_cost` | Estimated dollar cost for one bounded rerank call. | Lower is better at equal quality. | Lets us compare one-shot rerank against multi-round agent tool loops. |
| `log_path` | JSONL trace for the full AI run. | Must exist. | Audit trail for messages, tool results, usage, stderr, fallbacks, and command boundaries. |
| `bucket.<name>.*` | The same retrieval metrics sliced by deterministic query bucket: `semantic`, `path_symbol`, or `workflow`. | Depends on bucket. | Shows where a strategy actually wins instead of hiding regressions in the average. |
| `top_result_kind.<kind>.rate` | Fraction of cases where the top result came from `chunk`, `symbol`, `file_summary`, or fallback kind. | Depends. | Shows which index type dominates first rank. |
| `first_relevant_kind.<kind>.rate` | Among hit cases, fraction where the first relevant result came from that index type. | Depends. | Shows which index type actually finds correct evidence. |

## Code Explanation Metrics

`evaluate-explanations` measures answer quality after code has already been
provided to the model. This is separate from retrieval quality.

| Metric | Meaning | Good value | What it tells us |
| --- | --- | ---: | --- |
| `token_precision` | Generated explanation tokens that overlap the reference docstring. | Higher | Low values mean verbose or off-topic explanations. |
| `token_recall` | Reference docstring tokens covered by the generated explanation. | Higher | Low values mean the explanation missed important documented behavior. |
| `token_f1` | Harmonic mean of token precision and recall. | Higher | Cheap reproducible summary metric for docstring similarity. |
| `key_token_precision` / `key_token_recall` / `key_token_f1` | Same overlap after stop-word removal and simple token normalization. | Higher | Better signal for technical terms than raw token overlap. |
| `bigram_precision` / `bigram_recall` / `bigram_f1` | Two-token phrase overlap. | Higher | Stricter than token overlap; catches whether important phrases survive. |
| `prediction_tokens` | Mean generated explanation length. | Depends | Helps detect terse answers and expensive over-explanation. |
| `reference_tokens` | Mean reference docstring length. | Depends | Context for interpreting overlap scores. |
| `judge_purpose_accuracy` | Questionnaire score for correctly identifying what the code is for. | `4.0` | Catches wrong high-level explanations. |
| `judge_behavior_accuracy` | Questionnaire score for control flow, transformations, branches, loops, calls, and returned behavior. | `4.0` | Main semantic behavior metric. |
| `judge_api_contract` | Questionnaire score for inputs, outputs, side effects, and visible errors/exceptions. | `4.0` | Whether the answer helps a caller or maintainer. |
| `judge_groundedness` | Questionnaire score for claims supported by code/reference. | `4.0` | Penalizes hallucinated behavior. |
| `judge_specificity` | Questionnaire score for code-specific detail. | `4.0` | Penalizes generic explanations that could fit any function. |
| `judge_completeness` | Questionnaire score for important behavior coverage. | `4.0` | Whether the answer is useful beyond a one-line summary. |
| `judge_clarity` | Questionnaire score for concise, readable developer wording. | `4.0` | Separates correct but unusable explanations from good ones. |
| `judge_overall` | Weighted final score computed from the questionnaire. | `5.0` | Overall semantic explanation quality. |

Use overlap metrics for cheap regression checks. Use judge metrics for model
selection, but compare runs only when the same judge model and prompt were used.

## E2E Answer Metrics

`evaluate-answers` measures the product path after a user asks a repository
question:

```text
question -> retrieval/rerank -> bounded file context -> final answer -> optional judge
```

It is intentionally separate from `evaluate` and `evaluate-explanations`.
Retrieval-only Hit@K does not prove answer quality, and snippet explanation does
not prove the system found the right code.

| Metric | Meaning | Good value | What it tells us |
| --- | --- | ---: | --- |
| `file_hit` | At least one expected file appears in the retrieved/context candidate set. | `1.0` | Whether the answer model had any chance to use correct evidence. |
| `file_recall` | Expected files covered by candidates. | `1.0` | Critical for multi-file questions such as "where is user editing handled?" |
| `file_precision` | Retrieved files that are expected files. | Higher | How noisy the evidence bundle is before answer generation. |
| `file_mrr` | Reciprocal rank of the first expected file. | `1.0` | Whether the correct evidence is near the top. |
| `candidate_file_hit@1/3/5/K` | Whether any expected file appears in the top N retrieved files before context truncation. | `1.0` | Separates retrieval/rerank quality from later context selection. |
| `candidate_file_recall@1/3/5/K` | Expected file coverage in the top N retrieved files. | `1.0` | Shows whether a larger candidate pool contains the full answer bundle. |
| `context_file_hit` | Whether any expected file survives into the bounded context sent to the answer model. | `1.0` | If this is lower than candidate hit, context selection is losing evidence. |
| `context_file_recall` | Expected file coverage in the files actually read into context. | `1.0` | Main bundle-completeness metric for the answer model. |
| `context_file_precision` | Context files that are expected files. | Higher | Measures evidence noise after deduplication and context limits. |
| `planned_query_count` | Number of search probes used for the case. | Depends | Shows whether the run used single-query retrieval or agent-generated multi-query retrieval. |
| `planning_duration_ms` | Time spent asking the LLM to generate search probes. | Lower | Extra agentic planning overhead before retrieval. |
| `rerank_duration_ms` | Time spent in an optional final shared rerank over a merged planned-query candidate pool. | Lower | Separates reranker overhead from probe retrieval and answer generation. |
| `citation_count` | Number of structured citations returned by the answer model. | Depends | Detects uncited answers and citation spam. |
| `citation_path_valid_rate` | Citations whose path appears in the retrieved context. | `1.0` | Catches invented or stale file paths before judge scoring. |
| `citation_line_valid_rate` | Citations whose line range overlaps the retrieved excerpt for that path. | `1.0` | Catches line-number hallucinations and bad citation formatting. |
| `token_*`, `key_token_*`, `bigram_*` | Text overlap between final answer and reference answer. | Higher | Cheap deterministic regression signal; weak for paraphrases. |
| `judge_answer_correctness` | Questionnaire score for directly answering the question. | `4.0` | Main semantic answer metric. |
| `judge_evidence_grounding` | Questionnaire score for grounding in retrieved context/reference. | `4.0` | Penalizes unsupported architecture claims. |
| `judge_coverage` | Questionnaire score for covering required files, methods, and relationships. | `4.0` | Captures multi-file completeness. |
| `judge_citation_quality` | Questionnaire score for useful file/line evidence. | `4.0` | Whether the answer is inspectable by a developer. |
| `judge_specificity` | Questionnaire score for concrete code-specific detail. | `4.0` | Penalizes generic "this handles auth" answers. |
| `judge_hallucination_control` | Questionnaire score for avoiding invented files/APIs/line numbers. | `4.0` | Safety guard for code exploration. |
| `judge_overall` | Weighted final score from the answer judge rubric. | `5.0` | Overall answer quality with the configured judge. |
| `retrieval_duration_ms` | Search and rerank wall-clock time per case. | Lower | Whether candidate generation/rerank is the bottleneck. |
| `context_duration_ms` | Bounded file read/context assembly time per case. | Lower | Whether local file inspection is the bottleneck. |
| `generation_duration_ms` | Final answer generation time per case. | Lower | Whether the explainer model is the bottleneck. |
| `judge_duration_ms` | Optional judge time per case. | Lower | Benchmark-only overhead; not user-facing latency. |
| `answer_duration_ms_mean` | Mean wall-clock duration per case. | Lower | End-user latency for the measured answer pipeline. |

The default answer judge prompt is
[prompts/code-answer-judge.md](../prompts/code-answer-judge.md). Compare
`judge_*` metrics only when judge model, prompt, dataset, and context limits are
the same.

Saved answer reports can be judged after the fact:

```bash
uv run code-diver --help-all answer-report path/to/evaluate-answers.json --judge
```

For strongest validity, judge reports where each row contains `context_text`.
If `context_text` is missing, Code Diver reconstructs bounded context from the
saved file list and repository root; mark those metrics as reconstructed-context
judge metrics in research notes.

`evaluate-answers` also emits the standard statistical suffixes for every
numeric E2E metric: `_variance`, `_stddev`, `_stderr`, `_ci95_low`,
`_ci95_high`, and `_ci95_width`. Binary hit/validity metrics use Wilson
intervals; continuous overlap, latency, and judge scores use normal intervals.
On tiny smoke runs these intervals are intentionally wide and should prevent us
from overclaiming quality.

## Statistical Reliability

Every core quality metric now also reports a small statistical family:

| Suffix | Meaning | How to read it |
| --- | --- | --- |
| `_variance` | Sample variance across per-case values. | High variance means the strategy is inconsistent: it wins some cases and collapses on others. |
| `_stddev` | Standard deviation across per-case values. | Same signal as variance, in the metric's own units. |
| `_stderr` | Standard error of the mean. | Shrinks as the dataset grows; useful for comparing 100-case vs 1000-case runs. |
| `_ci95_low` / `_ci95_high` | 95% confidence interval for the metric mean. Binary hit metrics use Wilson intervals; continuous metrics use a normal interval over per-case scores. | If two hypotheses have heavily overlapping intervals, treat the apparent winner as unproven. |
| `_ci95_width` | Interval width. | Smaller means the estimate is more stable. Wide intervals mean we need more cases or more bucketed analysis before trusting the result. |

Example: `hit_rate@5=0.82` with `hit_rate@5_ci95_low=0.79` and `hit_rate@5_ci95_high=0.85` is materially more trustworthy than `hit_rate@5=0.84` with `[0.73, 0.91]`. On the 1000-case IntelliJ benchmark, compare both the mean and CI width. A quality gain smaller than the wider CI width is noise until proven by a larger or better-balanced dataset.

The statistics are emitted by `evaluate`, `experiment`, `evaluate-indexing`, and `evaluate-search-tools` because they all flow through the same evaluation metric service or direct-search metric helper.

## Derived Metrics

These are computed from the primary retrieval metrics and are meant to make failures easier to classify.

| Metric | Meaning | How to use it |
| --- | --- | --- |
| `multi_expected_rate` | Fraction of cases with more than one expected file. | If this is high, `Hit@1` is not enough; read recall and bundle metrics first. |
| `expected_files_mean` / `expected_files_p95` | Expected answer-set size. | Shows whether the dataset is single-target lookup or multi-file workflow search. |
| `retrieved_files_mean` | Mean number of deduplicated files returned. | Helps detect duplicate chunk pressure. |
| `unique_file_ratio@K` | Deduplicated file count divided by retrieved item count. | Low values mean top-k is clogged by repeated chunks from the same file. |
| `miss_rate@1` | `1 - hit_rate@1`. | First-result failure rate. Useful for user-visible answer quality. |
| `miss_rate@K` / `file_miss_rate@K` | `1 - hit_rate@K` or `1 - file_hit_rate@K`. | Candidate failure rate. If high, reranking cannot fix the run. |
| `coverage_gap@K` / `file_coverage_gap@K` | `1 - recall@K` or `1 - file_recall@K`. | Missing-answer rate for multi-target cases. |
| `rerank_headroom@3/5/K` | `hit_rate@N - hit_rate@1`. | Cases where a relevant item exists below rank 1. This estimates how much a reranker can still improve. |
| `bundle_complete_rate@K` | Fraction of cases where all expected files are covered. | The key metric for questions like "where is user editing handled?" |
| `bundle_partial_rate@K` | Fraction of cases where some, but not all, expected files are covered. | Shows when search finds the right area but not the whole workflow. |
| `bundle_empty_rate@K` | Fraction of cases with zero expected files covered. | Hard failure rate at file-bundle level. |
| `ndcg_per_second@K`, `map_per_second@K`, `recall_per_second@K` | Quality divided by mean query latency in seconds. | Efficiency metrics for choosing between local/API rerankers and deterministic search. |

Read `rerank_headroom@5` together with `file_coverage_gap@10`:

- High headroom, low coverage gap: ranking problem. Test stronger rerankers or reranker prompts.
- Low headroom, high coverage gap: candidate/index problem. Improve chunking, graph expansion, lexical/path search, or query decomposition.
- High bundle partial rate: search finds one entry point but misses related files. GraphRAG, workflow-specific routing, and multi-query expansion are the right next tests.

## Graph Trace Metrics

Hybrid search writes `hybrid_rank_stages` events when tracing is enabled. The `graph` object now contains:

| Field | Meaning |
| --- | --- |
| `requested_depth` | `hybrid_search.graph_depth` from config after hypothesis overrides. |
| `effective_depth` | Actual route-aware depth used by the graph profile. Workflow queries can be promoted deeper; semantic queries are capped shallow. |
| `requested_neighbor_limit` | Configured neighbor limit. |
| `effective_neighbor_limit` | Actual route-aware neighbor limit. |
| `candidate_count` | Number of graph-expanded candidates before final fusion. |
| `final_result_count` | Number of final top-k results that received non-zero graph score. |
| `final_result_rate` | `final_result_count / returned_results`. |

Graph depth is intentionally conservative. Code graphs have high fanout from imports, references, and containment edges; depth 2 can already produce hundreds or thousands of neighbors in large repositories. The current policy is route-aware:

- `workflow`: minimum depth 2, because multi-hop call/reference traversal can help.
- `path_symbol`: minimum depth 1, because exact-ish symbol/path queries usually need local neighbors.
- `semantic`: capped at depth 1, because distant graph neighbors often add noise and demote good vector hits.

Depth should be increased only when graph trace metrics show that graph candidates enter the final results and improve workflow bucket metrics without damaging semantic/path-symbol buckets.

## How To Read The Metrics

Use `hit_rate@10` only as the candidate-recall check. If it is low, the strategy misses the target files and reranking cannot save it.

Use `hit_rate@3`, `hit_rate@5`, and `mrr@10` next. These tell us whether the relevant item is high enough for a real AI searcher to inspect without burning reads.

Use `precision@10` to estimate token waste. A strategy with high hit rate and low precision can answer simple questions but will inflate context and cost.

Use `duration_ms` only together with backend details. JSON vector search is brute-force and slow for dense embeddings. Qdrant should be used for serious local/API embedding speed comparisons.

For AI indexing hypotheses, read quality and cost together:

1. Reject low `hit_rate@10`; it means candidate generation is failing.
2. Among acceptable candidate recall, optimize `hit_rate@3`, `hit_rate@5`, and `mrr@10`.
3. Among similar MRR, prefer lower `orchestrator_usage.total_tokens`, `orchestrator_usage.total_cost`, and `indexing_duration_ms`.
4. Use `indexed_items` and `precision@10` to detect indexes that are too broad and waste context.
5. Open `log_path` when a run is surprising; the log is the source of truth for what the model actually did.

## Reports And Charts

For one-off local analysis, write any eval command to JSON and render a static report:

```bash
uv run code-diver --config configs/intellij-community-vllm-qdrant.yml experiment --json \
  > .code-diver/reports/intellij-hypotheses.json
uv run python scripts/build_eval_report.py \
  .code-diver/reports/intellij-hypotheses.json \
  --output .code-diver/reports/intellij-hypotheses.html
```

The HTML report shows:

- one summary table with primary metrics and 95% CI bounds;
- one bar chart per metric with confidence whiskers;
- per-case distributions for hit, reciprocal rank, and recall when the JSON includes detailed results.

For long-running comparison suites, enable ClickHouse metrics and open Grafana at `http://localhost:3000`. The provisioned dashboard overlays strategies on the same panels for `Hit@1/3/5/10`, `MRR`, `nDCG`, `MAP`, runtime, and CI width. The important chart for reliability is CI width: a fast, high-scoring strategy with broad intervals is not a stable winner yet.

The ClickHouse `rag_eval_cases` table stores rich per-case fields, not just the final aggregate:

- chunk-level `hit`, `reciprocal_rank`, `precision`, and `recall`;
- file-level `file_hit`, `file_reciprocal_rank`, `file_precision_at_r`, and `file_recall`;
- ranking metrics `ndcg` and `average_precision`;
- `bucket`, `top_result_kind`, and `first_relevant_kind`;
- `expected_count`, `retrieved_count`, and `retrieved_file_count`.

Use this table to answer questions like "does BM25 only help path/symbol cases?", "which index kind actually produces first relevant hits?", and "is a strategy winning average recall while failing multi-file workflow cases?".

## Current `../protogen` Runs

Historical dataset: `datasets/protogen_eval.jsonl`, 10 repository-location cases, `limit=10`.

Current primary dataset: `datasets/protogen_eval_100.jsonl`, 100 informal code-search intent cases, `limit=10`. These cases ask questions like "where is authorization handled?", "where is a generation command created?", and "where are strategies run?", with expected paths validated against the sibling `../protogen` checkout.

Regenerate it with:

```bash
uv run python scripts/generate_protogen_eval.py --root ../protogen --output datasets/protogen_eval_100.jsonl --limit 100
```

The generator intentionally prioritizes informal intent queries over symbol lookup. Symbol cases are available as a fallback source, but the checked-in 100-case dataset is currently all `where-*` intent cases.

| Config | Embeddings | Indexing | Strategy | Items | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Duration |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `configs/protogen-baseline.yml` | hash-token-v1 | line chunks | vector | 2444 | 0.70 | 0.372 | n/a | n/a | n/a |
| `configs/protogen-symbols.yml` | hash-token-v1 | line+symbol+AST graph | vector | 8842 | 0.30 | 0.250 | 0.100 | 0.300 | 4.8s |
| `configs/protogen-symbols.yml` | hash-token-v1 | line+symbol+AST graph | recursive | 8842 | 0.50 | 0.298 | 0.070 | 0.500 | 19.1s |
| `configs/protogen-symbols.yml` | hash-token-v1 | line+symbol+AST graph | graph | 8842 | 0.30 | 0.220 | 0.100 | 0.300 | 7.6s |
| `configs/protogen-ollama-embeddings.yml` | local `mxbai-embed-large` | line+symbol+AST graph | vector | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 14.4s |
| `configs/protogen-ollama-embeddings.yml` | local `mxbai-embed-large` | line+symbol+AST graph | recursive | 8246 | 0.90 | 0.612 | 0.310 | 0.850 | 57.9s |
| `configs/protogen-ollama-embeddings.yml` | local `mxbai-embed-large` | line+symbol+AST graph | graph | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 17.1s |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | line+symbol+AST graph | vector | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 0.4s |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | line+symbol+AST graph | recursive | 8246 | 0.90 | 0.612 | 0.310 | 0.850 | 1.4s |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | line+symbol+AST graph | graph | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 3.8s |
| `configs/protogen-vertex-smoke.yml` | Vertex `gemini-embedding-2` | selected-file smoke index | vector | 603 | 0.70 | 0.700 | 0.470 | 0.700 | 6.5s |
| `configs/protogen-vertex-smoke.yml` | Vertex `gemini-embedding-2` | selected-file smoke index | recursive | 603 | 0.70 | 0.700 | 0.492 | 0.700 | 30.7s |
| `configs/protogen-vertex-smoke.yml` | Vertex `gemini-embedding-2` | selected-file smoke index | graph | 603 | 0.70 | 0.700 | 0.470 | 0.700 | 6.3s |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | line+symbol+AST graph | vector | existing local index | 0.89 | 0.723 | 0.405 | 0.855 | 3.4s search total, 34ms/query |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | fresh line+symbol index, AST containment graph | vector | 8246 | 0.89 | 0.723 | 0.405 | 0.855 | 2.9s search total, 29ms/query |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | fresh line+symbol index, AST containment graph | graph | 8246 | 0.89 | 0.723 | 0.405 | 0.855 | 3.0s search total, 30ms/query |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | fresh line+symbol index, deterministic hybrid fusion | `hybrid_candidates_no_llm` | 8246 | 0.90 | 0.734 | 0.448 | 0.865 | 7.8s search total, 78ms/query |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | fresh line+symbol index, deterministic hybrid fusion | `hybrid_candidates_graph_boost` | 8246 | 0.90 | 0.734 | 0.469 | 0.865 | 8.0s search total, 80ms/query |

`n/a` means the older run was recorded before full metric output was documented.

### Deterministic Hybrid Candidate Run

Run date: 2026-05-31. Dataset: `datasets/protogen_eval_100.jsonl`, 100 informal code-search cases. Config: `configs/protogen-ollama-qdrant.yml`.

Implementation notes:

- Added `hybrid` retrieval strategy below the agent boundary. It fuses vector scores, lexical term coverage, path coverage, symbol metadata, and graph neighbor scores into one ranked `SearchResult` list.
- Added YAML-configurable weights through `hybrid_search`, plus hypothesis-level overrides for comparing profiles.
- Added an inverted lexical index and cached item token profiles so hybrid search does not rescan and retokenize every item for every query.
- Fixed GraphRAG stale-artifact behavior so vector seed results are preserved when graph artifacts do not contain matching ids.
- Cached GraphRAG adjacency so graph retrieval no longer reloads the graph or scans every edge per query.
- Made broad reference edges and AST call edges configurable. For the protogen sandbox they are disabled because they made fresh indexing spend minutes of CPU after embeddings; the current graph keeps same-file, import, and AST containment edges.

Fresh benchmark after a local reindex:

| Strategy | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Total search | Mean/query | P95/query | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `vector_qdrant` | 0.89 | 0.723 | 0.405 | 0.855 | 2.9s | 29ms | 32ms | Control. |
| `recursive_qdrant` | 0.88 | 0.712 | 0.450 | 0.850 | 12.8s | 128ms | 145ms | More precise but lower hit/MRR/recall. |
| `graph_ast_qdrant` | 0.89 | 0.723 | 0.405 | 0.855 | 3.0s | 30ms | 31ms | After adjacency cache; current graph edges do not change ranking. |
| `hybrid_candidates_no_llm` | 0.90 | 0.734 | 0.448 | 0.865 | 7.8s | 78ms | 48ms | Best overall quality in this run. |
| `hybrid_candidates_lexical` | 0.89 | 0.714 | 0.460 | 0.865 | 7.8s | 78ms | 54ms | Better precision/recall than vector, worse MRR. |
| `hybrid_candidates_graph_boost` | 0.90 | 0.734 | 0.469 | 0.865 | 8.0s | 80ms | 50ms | Best precision among high-hit hybrid profiles. |
| `hybrid_candidates_path_symbol` | 0.89 | 0.722 | 0.450 | 0.855 | 7.7s | 77ms | 54ms | Path/symbol weighting alone is not enough. |

Interpretation:

- Deterministic hybrid fusion finally beats vector-only on the 100-case dataset: `+0.01 hit@10`, `+0.011 MRR`, `+0.043 precision`, and `+0.010 recall`, with zero LLM tokens.
- The gain is modest but meaningful because the previous agent-controlled hybrid toolsets were slower, more expensive, and less accurate.
- The current hybrid implementation is still not fast enough as the default interactive path. Most overhead is local Python scoring/index warmup, not model latency.
- Next optimization should move the lexical index into the persisted artifact or Qdrant payload/sparse vectors, so the first query does not pay the full build cost.

### File-Level Metrics Run

Run date: 2026-05-31. Same 100-case dataset and current Qdrant/graph artifacts.

| Strategy | Hit@1 | Hit@3 | File Hit@10 | File MRR@10 | File Precision@R | File Recall@10 | nDCG@10 | MAP@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.29 | 0.50 | 0.89 | 0.735 | 0.525 | 0.760 | 0.682 | 0.614 |
| `recursive_qdrant` | 0.27 | 0.46 | 0.88 | 0.727 | 0.510 | 0.750 | 0.671 | 0.601 |
| `graph_ast_qdrant` | 0.29 | 0.50 | 0.89 | 0.735 | 0.525 | 0.760 | 0.682 | 0.614 |
| `hybrid_candidates_no_llm` | 0.28 | 0.53 | 0.90 | 0.753 | 0.575 | 0.755 | 0.692 | 0.627 |
| `hybrid_candidates_lexical` | 0.29 | 0.54 | 0.89 | 0.730 | 0.530 | 0.755 | 0.675 | 0.605 |
| `hybrid_candidates_graph_boost` | 0.30 | 0.53 | 0.90 | 0.754 | 0.550 | 0.755 | 0.688 | 0.619 |
| `hybrid_candidates_llm_rerank` | 0.70 | 0.87 | 0.93 | 0.797 | 0.605 | 0.795 | 0.735 | 0.673 |
| `hybrid_rerank_file_first` | 0.73 | 0.88 | 0.93 | 0.818 | 0.635 | 0.800 | 0.752 | 0.694 |
| `hybrid_candidates_path_symbol` | 0.27 | 0.50 | 0.89 | 0.737 | 0.540 | 0.750 | 0.679 | 0.610 |

BM25/RRF follow-up:

| Strategy | Hit@1 | Hit@3 | File Hit@10 | File MRR@10 | File Precision@R | File Recall@10 | nDCG@10 | MAP@10 | Read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `hybrid_candidates_bm25_rrf` | 0.15 | 0.46 | 0.91 | 0.716 | 0.505 | 0.770 | 0.670 | 0.592 | Finds more relevant files, damages rank. |
| `hybrid_candidates_bm25_weighted` | 0.27 | 0.47 | 0.91 | 0.721 | 0.520 | 0.775 | 0.679 | 0.605 | Better than RRF for hit@1, still worse than coverage hybrid. |
| `hybrid_candidates_bm25_rrf_vector` | 0.15 | 0.45 | 0.92 | 0.738 | 0.540 | 0.770 | 0.684 | 0.611 | Best coverage, still bad first-rank quality. |

Router follow-up after `tool_router_v1`:

| Strategy | Hit@1 | Hit@3 | File Hit@10 | File MRR@10 | File Precision@R | File Recall@10 | nDCG@10 | MAP@10 | Mean/query | Read |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `vector_qdrant` | 0.29 | 0.50 | 0.89 | 0.735 | 0.525 | 0.760 | 0.682 | 0.614 | 30ms | Fast control. |
| `hybrid_candidates_no_llm` | 0.28 | 0.53 | 0.90 | 0.753 | 0.575 | 0.755 | 0.692 | 0.627 | 119ms | Best file cleanliness and MAP. |
| `hybrid_candidates_graph_boost` | 0.30 | 0.53 | 0.90 | 0.747 | 0.545 | 0.755 | 0.685 | 0.616 | 121ms | Better first rank, weaker overall file ordering. |
| `hybrid_candidates_bm25_rrf` | 0.15 | 0.46 | 0.91 | 0.716 | 0.505 | 0.770 | 0.670 | 0.592 | 129ms | Global BM25/RRF over-expands lexical matches. |
| `hybrid_candidates_bm25_weighted` | 0.27 | 0.47 | 0.91 | 0.721 | 0.520 | 0.775 | 0.679 | 0.605 | 129ms | Weighted BM25 preserves hit@1 better than RRF but still loses rank quality. |
| `hybrid_candidates_bm25_rrf_vector` | 0.15 | 0.45 | 0.92 | 0.738 | 0.540 | 0.770 | 0.684 | 0.611 | 129ms | Best coverage, bad first-screen quality. |
| `hybrid_candidates_routed` | 0.30 | 0.52 | 0.91 | 0.753 | 0.540 | 0.770 | 0.694 | 0.624 | 125ms | Best nDCG and good coverage/rank tradeoff; not yet cleaner than no-router hybrid. |

Interpretation:

- Hybrid improves the practical first-screen metrics: `hit@3`, file MRR, file precision@R, nDCG, and MAP.
- `hybrid_candidates_no_llm` has the best overall rank quality: `file_mrr@10=0.753`, `file_precision@R=0.575`, `ndcg@10=0.692`, `map@10=0.627`.
- `hybrid_candidates_graph_boost` has the best `hit@1` and chunk-level precision, but it gives up a little nDCG/MAP versus `hybrid_candidates_no_llm`.
- File recall is lower than old chunk-level recall because chunk-level recall counted repeated chunks from the same expected file. File-level recall is the more honest coverage metric.
- BM25 improves candidate coverage but hurts top-rank quality when applied globally. This is evidence for deterministic query routing: use BM25 strongly for exact/path/symbol queries, not for every informal semantic query.
- Router v1 confirms the direction: it beats global BM25 profiles on rank metrics and reaches the best `ndcg@10`, but it still needs route-bucket metrics and narrower triggers before it should replace `hybrid_candidates_no_llm`.

### Hybrid Indexing Run

Run date: 2026-05-31. Config: `configs/protogen-ollama-qdrant.yml`. The scanner indexed line chunks, symbol chunks, and file summaries into the same Qdrant collection.

Index size:

| Index | Items | Notes |
| --- | ---: | --- |
| Previous line+symbol index | 8246 | Line chunks plus symbol chunks. |
| Hybrid line+symbol+file-summary index | 9230 | Adds one `file_summary` item per indexed file. |

Overall result after reindex:

| Strategy | Hit@1 | Hit@3 | File Hit@10 | File MRR@10 | File Precision@R | File Recall@10 | nDCG@10 | MAP@10 | Mean/query |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.29 | 0.48 | 0.88 | 0.731 | 0.525 | 0.755 | 0.679 | 0.612 | 31ms |
| `hybrid_candidates_no_llm` | 0.28 | 0.49 | 0.89 | 0.747 | 0.570 | 0.745 | 0.684 | 0.619 | 131ms |
| `hybrid_candidates_routed` | 0.28 | 0.51 | 0.90 | 0.742 | 0.530 | 0.765 | 0.688 | 0.618 | 134ms |
| `hybrid_candidates_multi_index_routed` | 0.21 | 0.43 | 0.90 | 0.733 | 0.510 | 0.760 | 0.677 | 0.604 | 141ms |
| `hybrid_candidates_multi_index_guarded` | 0.28 | 0.46 | 0.90 | 0.750 | 0.535 | 0.760 | 0.689 | 0.620 | 136ms |

Bucket result:

| Bucket | Best observed strategy | Pattern |
| --- | --- | --- |
| `semantic` | `vector_qdrant` by file MRR: 0.797 | Dense vector search is currently best for broad informal concepts. Hybrid lexical/symbol signals can demote the right semantic candidate. |
| `path_symbol` | `hybrid_candidates_routed` / guarded by file MRR: about 0.790 | Routed lexical/path/symbol weighting helps exact-ish and structure-aware queries. |
| `workflow` | `hybrid_candidates_no_llm` / guarded by file MRR: 0.708 | Current graph expansion is not yet a clear win; graph edges need better call/reference coverage or query-aware traversal. |

Index-kind contribution:

| Strategy | Top chunk | Top symbol | Top file-summary | First relevant chunk | First relevant symbol | First relevant file-summary |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.47 | 0.52 | 0.01 | 0.466 | 0.534 | 0.000 |
| `hybrid_candidates_routed` | 0.43 | 0.54 | 0.03 | 0.456 | 0.533 | 0.011 |
| `hybrid_candidates_multi_index_routed` | 0.36 | 0.60 | 0.04 | 0.389 | 0.589 | 0.022 |
| `hybrid_candidates_multi_index_guarded` | 0.41 | 0.58 | 0.01 | 0.444 | 0.556 | 0.000 |

Interpretation:

- Multi-indexing itself is useful instrumentation, but naive file-summary boosting hurts rank quality.
- Symbol chunks are the strongest non-vector index type on this dataset: they account for more than half of first relevant hits.
- File summaries should stay as recall candidates or reranker context, not primary top-rank evidence.
- The next real quality lever is bucket-specific fusion: vector-first for `semantic`, routed symbol/path for `path_symbol`, and a better graph traversal/index for `workflow`.

### Modern GraphRAG Run

Run date: 2026-05-31. Config: `configs/protogen-ollama-qdrant.yml`. The graph was rebuilt with typed edges: `same_file_next`, `summarizes`, `imports`, `references`, `contains`, and `calls`.

Graph size:

| Nodes | Edges | Edge distribution |
| ---: | ---: | --- |
| 9230 | 91117 | `same_file_next=7262`, `summarizes=8167`, `imports=23671`, `references=26685`, `contains=9081`, `calls=16251` |

Overall result after query-aware typed traversal:

| Strategy | Hit@1 | Hit@3 | File Hit@10 | File MRR@10 | File Precision@R | File Recall@10 | nDCG@10 | MAP@10 | Mean/query |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.29 | 0.48 | 0.88 | 0.731 | 0.525 | 0.755 | 0.679 | 0.612 | 31ms |
| `hybrid_candidates_no_llm` | 0.28 | 0.46 | 0.89 | 0.741 | 0.555 | 0.750 | 0.683 | 0.616 | 136ms |
| `hybrid_candidates_routed` | 0.24 | 0.48 | 0.90 | 0.740 | 0.540 | 0.765 | 0.687 | 0.619 | 138ms |
| `hybrid_candidates_multi_index_guarded` | 0.24 | 0.45 | 0.90 | 0.737 | 0.535 | 0.760 | 0.682 | 0.613 | 140ms |
| `hybrid_candidates_modern_graphrag` | 0.23 | 0.44 | 0.90 | 0.737 | 0.535 | 0.760 | 0.682 | 0.613 | 141ms |

Bucket effect:

| Bucket | Control | GraphRAG result | Read |
| --- | ---: | ---: | --- |
| `workflow.ndcg@10` | `hybrid_candidates_no_llm=0.629` | `modern_graphrag=0.646` | Typed graph traversal helps multi-hop workflow coverage/order. |
| `workflow.file_mrr@10` | `hybrid_candidates_no_llm=0.691` | `modern_graphrag=0.700` | Small workflow rank gain. |
| `semantic.file_mrr@10` | `vector_qdrant=0.797` | `modern_graphrag=0.747` | Semantic queries should stay vector-first; graph and symbol pressure hurts rank. |
| `path_symbol.file_mrr@10` | `routed=0.774` | `modern_graphrag=0.773` | Graph is neutral; BM25/path/symbol carry this bucket. |

Interpretation:

- The graph implementation is now structurally useful: workflow nDCG and workflow file MRR improve versus the non-graph hybrid control.
- It is not yet a global rank winner. Adding many call/reference edges increases symbol pressure and hurts top-1/top-3.
- The correct next step is not higher graph weight. It is edge-quality diagnostics and graph-aware reranking: use graph paths as features after candidate generation, not as a blunt score multiplier.
- Sweeps are now slower because each hypothesis rebuilds in-memory graph/lexical indexes. The next performance task is shared experiment-level caches or persisted lexical/neighbor indexes.

## Direct Orchestrator Tool Runs

Current direct-provider runs on `configs/protogen-ollama-qdrant.yml` with Gemini orchestration and local `mxbai-embed-large` embeddings:

| Mode | Dataset | Hypothesis | Indexed/Search Items | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Tokens | Cost est. | Duration |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| indexing | `protogen_eval_100.jsonl` | `ai_index_tree_only` | 20 indexed | 0.19 | 0.19 | 0.019 | 0.120 | 22,136 | $0.0468 | 43.4s |
| indexing | `protogen_eval_100.jsonl` | `ai_index_symbols_only` | 14 indexed | 0.00 | 0.00 | 0.000 | 0.000 | 76,133 | $0.1272 | 135.3s |
| indexing | `protogen_eval_100.jsonl` | `ai_index_rg_only` | 14 indexed | 0.12 | 0.105 | 0.013 | 0.075 | 37,319 | $0.0673 | 28.8s |
| indexing | `protogen_eval_100.jsonl` | `ai_index_inspect_only` | 38 indexed | 0.31 | 0.31 | 0.031 | 0.190 | 26,183 | $0.0654 | 25.4s |
| indexing | `protogen_eval_100.jsonl` | `ai_selected_index` | 21 indexed | 0.18 | 0.168 | 0.018 | 0.110 | 31,299 | $0.0612 | 62.5s |
| search-tools | `protogen_eval.jsonl` | `ai_grep_only` | 10 cases | 0.80 | 0.80 | 0.575 | 0.767 | 178,158 | $0.3225 | 244.3s |
| search-tools | `protogen_eval.jsonl` | `vector_qdrant` | 10 cases | 0.70 | 0.65 | 0.500 | 0.700 | 143,310 | $0.2616 | 193.1s |
| baseline | `protogen_eval.jsonl` | direct vector retrieval | 10 cases | 0.90 | 0.663 | 0.310 | 0.900 | 0 | $0.0000 | 0.39s |

The first `ai_grep_only` row above is a historical mixed-tool run. Despite the name, the configured `grep_search` toolset exposed `inspect`, `tree`, `symbols`, `grep`, `rg`, and `read`, so it is not a clean single-tool comparison.

### Structured Agent Tool Comparison

Fresh comparison from 2026-05-30, same config and 10-case historical dataset:

```bash
uv run code-diver --config configs/protogen-ollama-qdrant.yml evaluate-search-tools --dataset datasets/protogen_eval.jsonl --hypothesis <name> --json
```

The isolated hypotheses use explicit `tools` in YAML, so the agent cannot silently mix unrelated tools. `ai_search_vector_only` exposes only `code_diver_search`; `ai_search_rg_only` exposes only `code_diver_rg`; `*_read` adds bounded source reading. The "after prompt/history fix" rows include dynamic prompt examples for the actually available tools and compressed structured tool observations in the next model turn. Full raw tool results are still kept in the JSONL trace logs.

| Run id | Hypothesis | Tools | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Model calls | Tool calls | Tokens | Cost est. | Total time | Mean/query | P95/query | Errors |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `91deebc3b17f` | `ai_search_vector_only` before prompt/history fix | `search` | 0.90 | 0.850 | 0.492 | 0.867 | 22 | 12 | 32,930 | $0.0839 | 54.6s | 5.46s | 7.79s | 1 |
| `78c4cf2e8594` | `ai_search_vector_only` after prompt/history fix | `search` | 1.00 | 0.867 | 0.632 | 0.917 | 21 | 11 | 32,147 | $0.0811 | 53.6s | 5.36s | 6.63s | 0 |
| `91deebc3b17f` | `ai_search_rg_only` before prompt/history fix | `rg` | 0.30 | 0.300 | 0.095 | 0.233 | 43 | 36 | 157,767 | $0.2735 | 119.8s | 11.98s | 26.01s | 3 |
| `64aabc11d0b5` | `ai_search_rg_only` after prompt/history fix | `rg` | 0.30 | 0.300 | 0.117 | 0.300 | 44 | 45 | 134,921 | $0.2405 | 134.8s | 13.48s | 29.82s | 6 |
| `7f5aaad434dc` | `ai_search_vector_read` | `search`, `read` | 0.80 | 0.800 | 0.633 | 0.767 | 34 | 31 | 109,992 | $0.2094 | 113.4s | 11.34s | 27.25s | 1 |
| `7f5aaad434dc` | `ai_search_rg_read` | `rg`, `read` | 0.40 | 0.400 | 0.350 | 0.400 | 44 | 45 | 279,758 | $0.4675 | 116.2s | 11.62s | 27.05s | 2 |
| `4b31e8155061` | `vector_qdrant` mixed toolset | `search`, `inspect`, `open`, `tree`, `symbols`, `grep`, `rg`, `read`, `evaluate` | 0.50 | 0.450 | 0.275 | 0.467 | 37 | 46 | 245,192 | $0.4119 | 124.6s | 12.46s | 42.55s | 1 |
| `7c70dd0eeb44` | `ai_grep_only` mixed toolset | `inspect`, `tree`, `symbols`, `grep`, `rg`, `read` | 0.40 | 0.400 | 0.250 | 0.400 | 44 | 55 | 370,271 | $0.6098 | 159.1s | 15.91s | 28.64s | 3 |

### Autonomous Hybrid Toolset Run

Run `a5210403d9b6` was executed on 2026-05-30 after the audit fixes were applied. It tested the new vector-plus-tool hypotheses on the same 10-case live smoke dataset. Trace logs live under `.code-diver/traces/orchestrator-search/a5210403d9b6/`.

| Run id | Hypothesis | Tools | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Model calls | Tool calls | Tokens | Cost est. | Total time | Mean/query | P95/query | Errors |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `a5210403d9b6` | `ai_search_vector_only` | `search` | 0.80 | 0.683 | 0.573 | 0.717 | 24 | 15 | 37,849 | $0.0888 | 88.1s | 8.81s | 39.10s | 2 |
| `a5210403d9b6` | `ai_search_vector_rg` | `search`, `rg` | 0.40 | 0.400 | 0.270 | 0.400 | 36 | 36 | 66,095 | $0.1318 | 140.3s | 14.03s | 48.77s | 5 |
| `a5210403d9b6` | `ai_search_vector_symbols` | `search`, `symbols` | 0.70 | 0.700 | 0.523 | 0.617 | 31 | 25 | 59,901 | $0.1287 | 131.9s | 13.19s | 54.28s | 3 |
| `a5210403d9b6` | `ai_search_vector_inspect` | `search`, `inspect` | 0.60 | 0.600 | 0.600 | 0.550 | 40 | 34 | 93,870 | $0.1799 | 105.5s | 10.55s | 23.99s | 3 |
| `a5210403d9b6` | `ai_search_vector_rg_read` | `search`, `rg`, `read` | 0.30 | 0.300 | 0.300 | 0.300 | 44 | 56 | 119,565 | $0.2201 | 109.3s | 10.93s | 24.01s | 6 |
| `a5210403d9b6` | `ai_search_vector_symbols_read` | `search`, `symbols`, `read` | 0.60 | 0.600 | 0.600 | 0.550 | 38 | 37 | 98,139 | $0.1818 | 90.3s | 9.03s | 28.04s | 3 |

Because the control row in `a5210403d9b6` had two model-loop failures and used a fallback model in the trace, it was repeated alone as run `6b87e3eef745`. The repeat is the better control measurement for the current code path:

| Run id | Hypothesis | Tools | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Model calls | Tool calls | Tokens | Cost est. | Total time | Mean/query | P95/query | Errors |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `6b87e3eef745` | `ai_search_vector_only` | `search` | 1.00 | 0.867 | 0.582 | 0.917 | 20 | 10 | 28,719 | $0.0776 | 45.8s | 4.58s | 5.75s | 0 |

Hybrid run conclusion:

- None of the new mixed toolsets beat the clean `ai_search_vector_only` repeat on `hit@10`, `mrr@10`, recall, tokens, cost, latency, or error count.
- `ai_search_vector_symbols` had slightly higher MRR than the noisy control row in `a5210403d9b6`, but it lost to the clean repeat and used about 2.1x tokens.
- Adding `rg` consistently hurt quality. Adding `read` increased tool calls and cost without improving recall.
- The next experiment should not expose more raw tools to the open-ended agent loop. Build deterministic hybrid candidate generation, then use one bounded LLM rerank/verification turn.

What changed after the prompt/history fix:

- `ai_search_vector_only` improved from `hit@10=0.90` to `1.00`, removed the only error, and slightly reduced tokens and latency. The important improvement is stability and ranking quality, not raw speed.
- `ai_search_rg_only` used fewer tokens after dropping the raw `matches` array from prompt history (`157.8k` to `134.9k`), but quality did not improve. The agent still burns rounds inventing broad regexes and frequently hits `max_rounds_exceeded`.
- Adding `read` to vector search increased precision but hurt total quality, cost, and latency. Source reading is useful for final verification, but exposing it as a free multi-round search tool makes the agent over-invest in reading.
- Mixed toolsets performed worse than the isolated vector tool. More tools increased planning ambiguity, token volume, and tail latency.

Current interpretation:

1. `code_diver_search` is the best agent-facing candidate tool in this benchmark. It gives the model ranked structured candidates with paths, titles, line ranges, and scores.
2. Free-form LLM-controlled `rg` is not a good primary retrieval loop for informal code-search queries. It can be useful when the query contains concrete identifiers, but it is weak for questions like "where is authorization handled?" because the model must guess lexical anchors.
3. `read` should be a controlled verification/rerank phase over a small candidate set, not an always-available exploratory tool.
4. The next architecture should be two-stage: deterministic/vector candidate generation first, then one bounded LLM rerank/answer turn with optional targeted reads. Avoid open-ended multi-round search for the default interactive path.

### AI Indexing Follow-Up

The parser fix also made `ai_index_inspect_only` complete instead of failing on Gemini output with trailing JSON. The fresh run `6893a890d162` indexed only 7 items in 10.2s with 18,535 tokens and scored `hit@10=0.0` on the 100-case dataset. This is an infrastructure success but a strategy failure: a tiny LLM-selected index undercovers the repository. For indexing, the agent needs either a deterministic base index plus AI annotations, or a much more systematic planner that covers modules, symbols, routes, commands, configs, and workflows before selecting vector payloads.

## Local Vs API Read

Based on current measured retrieval metrics, the local Ollama embedding model is better than the hash baseline by a large margin on `../protogen`: `hit@10` improves to `0.90`, and `mrr@10` improves to `0.663`.

This does not yet prove local embeddings are better than Gemini/Vertex embeddings. Vertex now works through refreshed ADC, but the recorded Vertex run is a selected-file smoke index, not a full-repository benchmark. Full Vertex indexing is possible, but `gemini-embedding-2` on Vertex currently behaves as one-content-per-request in our SDK path, so a full 8k-item run needs explicit cost/time budgeting or more aggressive parallelism.

Practical conclusion right now:

- Use local `mxbai-embed-large` for fast iteration, privacy, and no per-token embedding cost.
- Use Qdrant for local embeddings; embedded Qdrant reduced vector evaluation from `14.4s` to `0.4s` on the same dataset.
- Use Gemini/Vertex embeddings when we need a stronger semantic model and can pay API latency/cost.
- Keep hash embeddings only as a reproducible control baseline, not as a quality target.

## Known Measurement Limits

- `datasets/protogen_eval.jsonl` has only 10 cases and is useful for quick live API checks, not final confidence.
- `datasets/protogen_eval_100.jsonl` has 100 informal intent cases and is the primary dataset for broader quality comparisons.
- Metrics evaluate retrieval, not final answer correctness.
- `duration_ms` includes Python implementation overhead and JSON vector store scans.
- Recursive search currently increases latency significantly and does not always improve quality over strong embeddings.
- Graph retrieval currently expands useful same-file/import/AST containment neighbors, but still needs query-aware edge policies to beat vector search consistently.
- The protogen GraphRAG config currently disables broad reference edges and AST call edges because they are too expensive for blocking sandbox indexing. They should return as bounded or incremental graph-building stages.
