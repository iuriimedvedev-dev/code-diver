# Agentic Search And Indexing - 2026-06-01

## Goal

Use the LLM where deterministic retrieval is weak:

- rewrite and retry searches;
- combine vector, regex, symbols, tree, inspect, read, and rerank tools;
- rank structured candidates after several evidence passes;
- index code with AI-selected ranges grounded in tool evidence.

This is separate from deterministic hybrid search. Deterministic search remains the fast default; agentic search is the quality path for hard or ambiguous queries.

## Search Runtime Changes

`DirectSearchOrchestrator` now has an adaptive evidence gate.

For hypotheses whose name contains `adaptive`, `agentic`, or `deep`:

- a final answer is rejected until candidate-producing evidence exists;
- at least two candidate/evidence passes are required before final results;
- if `code_diver_rerank` is available, final results are rejected until rerank has been called;
- runtime feedback is appended to the model history instead of silently accepting a weak answer.

The prompt now explicitly instructs the model to:

- start with `code_diver_search`;
- retry with a rewritten query or different tool when recall is weak;
- use scoped symbols/rg/grep/inspect as second-pass probes;
- call `code_diver_rerank` after candidates exist;
- read only small final ranges.

## Candidate Bank

`DirectToolExecutor` now remembers candidates recursively:

- top-level `candidates` from `code_diver_search`, `rg`, `grep`, and `symbols`;
- nested `sections[].result.candidates` from `code_diver_inspect`.

This lets `code_diver_rerank` rank candidates produced by all discovery tools, not just vector search.

## Indexing Runtime Changes

`DirectIndexingOrchestrator` now rejects `index_items` returned before any successful tool evidence.

The model must first use read-only tools, then return selected ranges. This prevents ungrounded AI indexing where the model invents paths or line ranges from repository priors.

The indexing prompt now frames indexing as AI-guided:

- form hypotheses from the eval queries;
- inspect tree/symbol/regex evidence;
- read only focused ranges;
- save fewer high-signal ranges, not broad dumps.

## Configured Hypotheses

Added:

- `ai_search_adaptive_agentic_rerank`
- `ai_adaptive_selected_index`

Both use Vertex `gemini-3.1-flash-lite` by default in the protogen config.

## Tests

Added/updated unit coverage for:

- adaptive search rejecting premature final answers;
- reranking candidates discovered through `inspect`;
- AI indexing rejecting ungrounded `index_items`;
- prompt policy for adaptive multi-pass search.

## Next Evaluation

Run the adaptive search hypothesis on `protogen_eval_100` and compare against:

- bounded `hybrid_rerank_flash_lite_top20_compact`;
- bounded `hybrid_rerank_flash_lite_file_first`;
- previous direct orchestrator rerank.

Expected tradeoff:

- higher cost/latency than bounded rerank;
- better recovery on cases where deterministic candidate generation misses or ranks weak evidence;
- better logs for failure analysis because tool use and runtime feedback are fully recorded.

## Smoke Eval

Dataset: first 10 cases from `datasets/protogen_eval_100.jsonl`

Run ID: `4e228d027354`

Hypothesis: `ai_search_adaptive_agentic_rerank`

| Metric | Value |
| --- | ---: |
| cases | 10 |
| Hit@1 | 0.700 |
| Hit@3 | 0.800 |
| Hit@10 | 0.900 |
| MRR@10 | 0.775 |
| nDCG@10 | 0.572 |
| mean latency | 12966 ms |
| p95 latency | 22037 ms |
| total tokens | 206,885 |
| cost | $0.062 |
| tool calls | 43 |

Tool calls in the smoke run:

| Tool | Calls |
| --- | ---: |
| `code_diver_search` | 11 |
| `code_diver_rerank` | 8 |
| `code_diver_read` | 15 |
| `code_diver_rg` | 6 |
| `code_diver_symbols` | 2 |
| `code_diver_grep` | 1 |

`adaptive_evidence_required` fired 4 times, which confirms the runtime rejected premature final answers and pushed the model back into tool use.

Interpretation:

- The loop works: the model uses multiple tools and reranks grounded candidates.
- It is too slow and expensive to be the default path.
- Next optimization should route into this mode only for hard queries, or after deterministic/compact rerank confidence is low.
