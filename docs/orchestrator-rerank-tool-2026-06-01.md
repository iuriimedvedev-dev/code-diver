# Orchestrator Rerank Tool - 2026-06-01

## What Changed

The direct search orchestrator now supports a dedicated AI ranking tool:

- `code_diver_search` remains candidate generation.
- `code_diver_rg`, `code_diver_grep`, `code_diver_symbols`, and `code_diver_tree` remain exact/structural probes.
- `code_diver_rerank` is a separate ranking tool over structured candidates.
- `code_diver_read` remains verification only.

The orchestrator runtime executes independent tools in parallel, but `code_diver_rerank` is marked `parallel_safe=false` because it depends on candidates produced by previous tools.

## Implementation Notes

- `code_diver_search` now returns compact previews in addition to path, title, lines, score, and index kind.
- `DirectToolExecutor` keeps a bounded candidate bank from previous candidate-producing tools.
- `code_diver_rerank` can rerank explicit candidates, selected candidate IDs, or the current candidate bank.
- Tool-level rerank model usage is merged into orchestrator usage metrics.
- Rerank hypotheses are enforced: if the model tries to return final results before calling `code_diver_rerank`, the runtime inserts the rerank tool call and gives the model another turn.
- Final short answers are extended with the latest reranked candidate list up to `limit`, so Hit@10 is not destroyed when the model only names 1-3 files.

## Algorithms And Tool Responsibilities

| Tool / strategy | Role | Best for | Weakness |
| --- | --- | --- | --- |
| `code_diver_search` | Hybrid/vector candidate generation | Semantic and informal code-navigation queries | Final ordering is weaker than LLM rerank |
| `code_diver_rg` | Regex/exact probe | Concrete anchors, routes, flags, config keys, symbol alternatives | Needs good query terms |
| `code_diver_grep` | Literal probe | Known exact strings | Not semantic |
| `code_diver_symbols` | Structural probe | Classes, methods, commands, handlers, models | Should be scoped after search |
| `code_diver_tree` | Repository map | Path/package/config discovery | Not behavior-aware |
| `code_diver_rerank` | AI final ordering | Ambiguous semantic/workflow ranking | Adds model turns and latency |
| `code_diver_read` | Verification | Proving final top candidates | Expensive if used for discovery |

## Full Eval

Dataset: `datasets/protogen_eval_100.jsonl`

Mode: `evaluate-search-tools --hypothesis ai_search_vector_rerank`

Run ID: `287dc8ec5431`

| Metric | Value |
| --- | ---: |
| cases | 100 |
| hit_rate@1 | 0.780 |
| hit_rate@3 | 0.850 |
| hit_rate@10 | 0.850 |
| mrr@10 | 0.815 |
| ndcg@10 | 0.712 |
| map@10 | 0.669 |
| mean latency | 10466 ms |
| p95 latency | 19985 ms |
| total tokens | 1,253,250 |
| total cost | $0.415 |
| tool calls | 222 |
| model turns | 316 |
| rerank tool calls | 105 |
| failures | 0 |

Rerank tool usage inside the run:

| Calls | Input tokens | Output tokens | Total tokens | Cost |
| ---: | ---: | ---: | ---: | ---: |
| 105 | 137,845 | 11,060 | 161,286 | $0.051 |

## Comparison

| Mode | Hit@1 | Hit@10 | MRR@10 | nDCG@10 | Cost / 100 | Mean ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bounded `hybrid_rerank_flash_lite_top20_compact` | 0.780 | 0.910 | 0.835 | 0.763 | $0.135 | 2194 |
| bounded `hybrid_rerank_flash_lite_file_first` | 0.780 | 0.930 | 0.842 | 0.776 | $0.325 | 3322 |
| orchestrator `ai_search_vector_rerank` | 0.780 | 0.850 | 0.815 | 0.712 | $0.415 | 10466 |
| deterministic guarded hybrid | 0.640 | 0.900 | 0.734 | 0.692 | $0 | 140 |

## Interpretation

The architecture is now correct: the orchestrator can call search tools, then call a distinct AI rerank tool, then return verified ranked paths.

The current orchestrator-tool mode is not yet the production default:

- It matches bounded compact rerank on Hit@1.
- It loses on Hit@10, nDCG, latency, and cost.
- Most cost is orchestration turns, not rerank itself.
- The bounded pipeline remains the best default for fast, reproducible search.

The orchestrator-tool mode should be used for research and harder queries where adaptive probing matters. To make it competitive, the next work is:

1. Reduce model turns: after rerank, auto-return reranked candidates unless read verification is explicitly required.
2. Route exact/path/config queries away from LLM orchestration.
3. Let `code_diver_rerank` operate over merged candidates from search + rg + symbols, not only vector candidates.
4. Add stage-level candidate logs: vector rank, regex rank, symbol rank, rerank rank, final rank.
5. Add a fast local cross-encoder/late-interaction reranker to compare against Flash-Lite.

## Indexing Hypotheses Tested

Two indexing changes were tested and rejected before commit:

- Prefixing embedding text with structural metadata (`index_kind`, `kind`, `symbol`, `lines`) hurt vector Hit@1.
- Increasing `embedding.max_input_chars` from `400` to `900` increased recall in some buckets but hurt rank-one quality, especially workflow.

The local Qdrant index was restored to the baseline embedding text and `max_input_chars=400`.

Conclusion: indexing should improve next through better chunk boundaries, code-specialized embeddings, and hard-negative-driven reranker training, not by naively adding metadata prefixes to the local mxbai embedding input.
