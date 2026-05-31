# Optimization Audit

Date: 2026-05-30

## Claude Code Audit Status

Requested command: run Claude Code CLI with `claude-opus-4-8` for a long read-only audit.

Local Claude Code is installed (`2.1.112`) and supports the needed flags: `--model`, `--effort`, `--allowedTools`, `--disallowedTools`, and `--output-format json`.

The external Claude run was approved after explicit user confirmation and completed successfully.

Run metadata:

| Field | Value |
| --- | --- |
| Model | `claude-opus-4-8` |
| CLI | Claude Code `2.1.112` |
| Mode | read-only audit, `Edit`/`Write`/`MultiEdit` disallowed |
| Output | `.code-diver/claude-opus-audit.json` |
| Duration | 204.1s |
| Turns | 30 |
| Cost | $4.3753 |
| Terminal reason | `completed` |

Claude's audit confirmed the main local findings and added three concrete issues this report originally missed: JSON-store indexing-eval isolation, reopening Qdrant/provider per `code_diver_search` tool call, and model-agnostic cost estimation.

Follow-up status:

| Commit | Change |
| --- | --- |
| `d6abef1` | Fixed JSON-store indexing artifact isolation, reused vector provider/store/strategy per search-tool hypothesis, made cost estimates model-aware, compacted search prompt history, and added unit coverage. |
| `798e59b` | Added isolated hybrid search hypotheses for `search+rg`, `search+symbols`, `search+inspect`, and bounded read variants. |
| this change | Added deterministic hybrid retrieval below the agent boundary, graph fallback/perf fixes, and YAML hypothesis overrides. |
| this change | Added deep quality-doubling research with Claude Opus brainstorm and external paper synthesis. |

Verification after those commits:

| Check | Result |
| --- | --- |
| Full test suite | `73 passed in 11.57s` |
| Config smoke load | 24 hypotheses loaded; new vector hybrid hypotheses present |
| Live hybrid eval | Run `a5210403d9b6`, 6 hypotheses, completed |
| Live control repeat | Run `6b87e3eef745`, `ai_search_vector_only`, completed with 0 errors |
| Deterministic hybrid eval | 100-case local run: best hybrid `hit@10=0.90`, `mrr@10=0.734`, `precision@10=0.448`, `recall@10=0.865` |
| Quality doubling audit | Claude Opus read-only brainstorm completed in 197.1s, 28 turns, $3.6095 |

## Executive Summary

The current system already has the right experimental shape: config-first CLI, Qdrant, reproducible datasets, trace logs, direct provider orchestration, and isolated tool hypotheses. The strongest measured path is also clear: expose a structured vector candidate tool to the model, not raw `rg` as the primary search loop.

Highest-leverage optimizations:

1. Replace open-ended multi-round search with a two-stage pipeline: cheap candidate generation first, one bounded LLM rerank/answer turn second.
2. Add hybrid retrieval: vector + BM25/sparse lexical + path/symbol boosts + graph signals.
3. Make GraphRAG deterministic and query-aware: AST/LSP/tree-sitter graph edges first, bounded traversal second, LLM graph extraction last if ever.
4. Replace fixed line-window chunks with typed, multi-granularity code items: file summaries, symbols, routes/commands/configs, tests, and chunk windows.
5. Move the eval harness out of `cli.py` into services so experiments are easier to parallelize, persist, and test.
6. Completed the correctness fixes found by Claude before running the latest comparison: JSON-store eval isolation, per-tool-call Qdrant reopen, and model-aware cost accounting.

The latest stable 10-case live eval strongly supports this direction:

| Hypothesis | Hit@10 | MRR@10 | Tokens | Duration | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| `ai_search_vector_only` | 1.00 | 0.867 | 28.7k | 45.8s | 0 |
| `ai_search_rg_only` | 0.30 | 0.300 | 134.9k | 134.8s | 6 |
| `ai_search_vector_read` | 0.80 | 0.800 | 110.0k | 113.4s | 1 |
| `ai_search_rg_read` | 0.40 | 0.400 | 279.8k | 116.2s | 2 |

The latest 100-case local eval shows the first deterministic hybrid win:

| Hypothesis | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Mean/query | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `vector_qdrant` | 0.89 | 0.723 | 0.405 | 0.855 | 29ms | 0 |
| `hybrid_candidates_no_llm` | 0.90 | 0.734 | 0.448 | 0.865 | 78ms | 0 |
| `hybrid_candidates_graph_boost` | 0.90 | 0.734 | 0.469 | 0.865 | 80ms | 0 |

Precision note: `precision@10=0.469` is close to the structural ceiling for this dataset shape because most cases expect only one or two files but the metric divides by a fixed 10 result slots. The next metrics commit should add file-level precision@R, nDCG@10, MAP, hit@1, and hit@3 before optimizing aggressively for precision.

## External Research Notes

Recent code-RAG work aligns with our findings:

- A 2026 codebase GraphRAG benchmark reports that vector-only retrieval struggles with multi-hop architecture questions and that deterministic AST-derived graphs provide better coverage and lower indexing cost than LLM-extracted graphs.
- RANGER uses a repository graph with dual-stage retrieval: entity queries use fast graph lookups, while natural-language queries use guided graph exploration. Its paper also reports that pairing graph retrieval with BM25 improved exact match in code completion.
- Clue-RAG uses multi-partite nodes over chunks, knowledge units, and entities, plus query-driven iterative retrieval. It reports better accuracy/F1 while reducing indexing costs and can match or beat baselines without LLM indexing.
- Current commercial code retrieval systems advertise the same direction: hybrid BM25 + vector fusion, graph centrality/path ranking, type filters, and token-budgeted output.
- Claude Opus 4.8 is available as `claude-opus-4-8`; official docs describe it as intended for long-horizon agentic coding, with improved tool triggering and long-context behavior. That makes it a reasonable auditor, but not a reason to make our runtime depend on open-ended agent loops.

References:

- https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-8
- https://code.claude.com/docs/en/cli-usage
- https://arxiv.org/abs/2601.08773
- https://arxiv.org/abs/2509.25257
- https://arxiv.org/abs/2507.08445
- https://codixing.com/

## Architecture Risks

### 1. `cli.py` Is The God Module

`src/code_diver/cli.py` owns command parsing, service construction, eval loops, metrics mapping, direct search orchestration, collection naming, graph indexing, and JSON output. The file imports almost every subsystem and contains long orchestration functions such as `cmd_evaluate_indexing` and `cmd_evaluate_search_tools`.

Evidence:

- Command setup lives in `build_parser` around `src/code_diver/cli.py:66`.
- Direct indexing orchestration lives in `cmd_evaluate_indexing` around `src/code_diver/cli.py:367`.
- Direct search-tool eval lives in `cmd_evaluate_search_tools` around `src/code_diver/cli.py:464`.
- Factories and hypothesis resolution live in the same file around `src/code_diver/cli.py:594`.

Risk: every new experiment increases coupling. Parallel eval execution, richer metrics, per-case logs, and retry policy will all be harder while they live in CLI command handlers.

Proposal: extract:

- `EvaluateIndexingCommand`
- `EvaluateSearchToolsCommand`
- `SearchToolEvaluationService`
- `IndexingHypothesisRunner`
- `AppFactory` or explicit provider/store factories

### 1.1 Search Tool Handler Reopens Qdrant Per Tool Call

Claude found that `make_search_tool_handler` constructs a new vector store and embedding provider for every `code_diver_search` call. On embedded Qdrant this reopens the on-disk client repeatedly; under concurrency it is both slow and a potential file-lock hazard.

Evidence:

- `make_search_tool_handler` builds the store/provider inside the nested `handle` function around `src/code_diver/cli.py:748`.
- `QdrantVectorStore` opens embedded/local Qdrant in its constructor around `src/code_diver/store/qdrant_vector_store.py:31`.

Proposal: build the vector store, provider, and retrieval strategy once per hypothesis run, inject the handler, and close the store after the hypothesis completes.

Status: fixed in `d6abef1` for search-tool evaluation. The handler now accepts an injected retrieval strategy, and the eval command owns provider/store lifecycle per hypothesis.

### 2. Direct Agent Search Is Still An Open-Ended Loop

`DirectSearchOrchestrator` allows up to 5 model rounds per case and appends full assistant/tool history into each next prompt. It now compresses observations, but the control policy is still "let the model decide whether to keep searching."

Evidence:

- `MAX_ROUNDS = 5` at `src/code_diver/agent/direct_search_orchestrator.py:21`.
- Round loop and prompt rebuild at `src/code_diver/agent/direct_search_orchestrator.py:68`.
- No deterministic early-stop exists after high-confidence candidates; the model must choose to return `results`.

Risk: latency and cost are dominated by model round-trips, not local retrieval. The failed `rg_only` runs show this directly.

Proposal: create a deterministic one-shot mode:

1. Generate candidates using configured retrieval tools without the LLM.
2. Normalize candidates into one schema.
3. Invoke the LLM once to rerank and explain.
4. Optionally read only the top 3 ranges for verification.

### 3. GraphRAG Is Built, But Not Yet Query-Aware

`GraphRetrievalStrategy` seeds with vector results, expands neighbors with static edge weights, then sorts by propagated score. It does not inspect query intent, edge kinds, language, path kind, symbol kind, or task type.

Evidence:

- Graph expansion is generic in `src/code_diver/strategies/graph_retrieval_strategy.py`.
- Edge construction uses same-file, imports, lexical references, containment, and Python calls in `src/code_diver/graph/code_graph_builder.py:28`.
- Reference edges tokenize every item and link by symbol names with a coarse global cap in `src/code_diver/graph/code_graph_builder.py:98`.

Risk: graph expansion can add related but irrelevant items. This explains why GraphRAG has not beaten vector search despite adding AST edges.

Proposal: add query-aware graph policies:

- "where is command registered?" prefers call/reference/config/CLI files.
- "where is auth handled?" prefers routes, middleware, dependencies, security modules.
- "where is this strategy run?" prefers callers and orchestrators.
- "where are tests?" prefers test edges and filename/path boosts.

## Retrieval And Indexing Issues

### Fixed Line Windows Are A Weak Default

`CodebaseScanner` chunks files by fixed line windows and optionally adds symbol chunks. This is inspectable and easy to test, but it produces many low-semantic chunks and duplicates context.

Evidence:

- Fixed line chunking is in `src/code_diver/services/codebase_scanner.py:143`.
- Symbol chunks are appended next to line chunks in `src/code_diver/services/codebase_scanner.py:102`.

Proposal:

- Keep file-window chunks as fallback.
- Add typed code items:
  - `file_summary`
  - `symbol`
  - `class`
  - `route`
  - `command`
  - `config`
  - `test`
  - `workflow`
- Store `language`, `kind`, `symbol`, `path_parts`, `imports`, `exports`, and `defined_names` as payload fields.

### AI-Selected Indexing Undercovers The Repo

`ai_index_inspect_only` completing with 7 indexed items and `hit@10=0.0` proves the current selected-index mode is not a viable primary indexer.

Proposal:

- Make deterministic scanner index mandatory.
- Let AI add annotations/summaries/tags to deterministic items instead of selecting the only index.
- If selected indexes remain useful, require module coverage quotas:
  - top-level dirs
  - service/controller/repository layers
  - CLI entrypoints
  - config and infra files
  - tests

### Qdrant Payload Is Too Flat

`QdrantVectorStore` stores one dense vector and a serialized `CodeItem`. There are no payload indexes, sparse vectors, named vectors, or filters.

Evidence:

- Collection creation uses only one dense vector config at `src/code_diver/store/qdrant_vector_store.py:60`.
- Search uses only dense `query_points` at `src/code_diver/store/qdrant_vector_store.py:104`.

Proposal:

- Add payload fields outside the serialized item: path, language, kind, symbol, start/end lines, source, module.
- Add Qdrant payload indexes for `path`, `kind`, `language`, and `symbol`.
- Add sparse/BM25-style vectors or a sidecar lexical index.
- Add named vectors when testing multiple embedding models or item representations.

### Indexing Eval Isolation Only Covers Qdrant

Claude identified a correctness bug: `config_for_indexing_hypothesis` only suffixes the Qdrant collection and graph artifact. If a JSON store config is used with `evaluate-indexing`, all hypotheses share `config.artifact`, overwrite each other's index, and can contaminate results.

Evidence:

- `config_for_indexing_hypothesis` changes only `storage.qdrant.collection` and `graph.artifact` around `src/code_diver/cli.py:696`.
- `store_label` still points JSON-backed stores at `config.artifact`.

Proposal: suffix the JSON artifact path with `<hypothesis>_<run_id>` exactly like the Qdrant collection. Add a unit test covering Qdrant and JSON configs.

Status: fixed in `d6abef1`. JSON artifacts, Qdrant collections, and graph artifacts are isolated by hypothesis and run id.

## Search Orchestration Issues

### Raw `rg` Is Too Low-Level For The Agent

`RgService` returns structured candidates, but ranking is based mostly on match count and lexical evidence lines.

Evidence:

- Candidate scoring is `0.45 + matchCount * 0.08` in `src/code_diver/inspection/rg_service.py:119`.

Risk: for informal queries, the model must invent regex anchors. This produced high token use and many `max_rounds_exceeded` failures.

Proposal:

- Do not expose raw `rg` as the default primary search tool.
- Add a deterministic lexical retrieval tool that:
  - expands query terms with tokenizer/path/symbol aliases;
  - runs multiple lexical probes;
  - aggregates by file;
  - returns ranked candidates with confidence, matched terms, and line spans.
- Keep raw `rg` for explicit identifier/file searches.

### `read` Should Be A Verification Phase

`vector+read` increased precision but cost more and reduced quality. The model used reads as exploration instead of verification.

Proposal:

- Hide `read` in default search hypotheses.
- Add controlled `verify_top_candidates` step that reads a small number of candidate ranges.
- Feed compressed snippets into a single rerank prompt.

## Token, Cost, And Latency Bottlenecks

1. Model round-trips dominate search-tool eval latency.
2. Prompt history still grows by round, even after compression.
3. Mixed toolsets increase planning ambiguity and tool-call volume.
4. Vertex embeddings currently embed one content at a time.
5. Search-tool vector access used to reopen the vector store/provider per tool call; this is fixed for search-tool evaluation in `d6abef1`.
6. Full trace prompts are useful for audits but expensive if replayed into subsequent prompts.
7. Cost estimates are now model-aware for the configured Gemini, OpenAI, Claude, and local model families, but the price table should still move to config before serious cost accounting.

Evidence:

- Search-tool eval loops cases serially in `src/code_diver/cli.py:488`.
- The orchestrator itself runs each case as a model/tool loop in `src/code_diver/agent/direct_search_orchestrator.py:68`.
- Vertex document embeddings call the parent provider once per text in `src/code_diver/providers/vertex_embedding_provider.py:48`.
- Historical versions of `make_search_tool_handler` created a fresh vector store/provider inside every tool call.
- Historical versions of `ModelCostEstimator` used flat pricing regardless of actual model.

Proposals:

- Add `--workers` to `evaluate-search-tools` for case-level parallelism when providers allow it.
- Add hard prompt-history budget in tokens, not only JSON character compression.
- Add one-shot rerank mode with max one generation call per case.
- Add provider-level rate limiter and retry policy with backoff/jitter.
- Batch Vertex embeddings if the SDK/API path supports it; if not, document expected time and expose higher safe concurrency.
- Move `ModelCostEstimator` pricing to a YAML/model registry and persist the price table version in metrics.

## Evaluation And Metrics Improvements

Current metrics are useful, but they are not yet sufficient to choose a production architecture.

Add:

- task type per eval case: `locate`, `trace`, `architecture`, `config`, `test`, `workflow`, `api`, `security`, `cli`.
- per-stage metrics:
  - candidate generation time
  - vector time
  - lexical time
  - graph expansion time
  - LLM rerank time
  - read/verification time
- token budget metrics:
  - candidate JSON bytes
  - snippet tokens
  - prompt tokens per turn
  - output tokens per turn
- failure taxonomy:
  - no JSON
  - no results
  - max rounds
  - tool error
  - provider timeout
  - empty candidate set
- answer-level evaluation later, but keep retrieval metrics first.

The 100-case dataset should become the default for quality decisions. The 10-case dataset is fine for live API smoke checks only.

## Provider And Model Risks

1. Defaults point at `gemini-3.5-flash` and `gemini-embedding-2`, but provider availability and model names move quickly.
2. The generation provider uses `v1alpha` and `thinking_budget`; this should be tested regularly against live API behavior.
3. Cost estimates are model-aware for known model families now, but prices can still drift and should move to configuration with a recorded price-table version.
4. Vertex auth is ADC/project/location based; AI Studio API keys are not Vertex credentials.
5. OpenAI-compatible local embedding paths should be treated as local provider profiles, not as OpenAI proper.

Proposals:

- Add `code-diver doctor providers` to smoke generation and embeddings for each configured provider.
- Persist provider/model/version/dimensions in every run row and report.
- Add a model registry config with pricing and capabilities rather than hardcoding in cost estimator.
- Add provider-specific timeout/retry/rate-limit config.

## Concrete Implementation Plan

### Quick Wins Under 1 Day

1. Done: compact search prompt history and keep full traces out of repeated model turns.
2. Done: make `ModelCostEstimator` model-aware for current provider families.
3. Done: reuse vector store/provider/retrieval strategy per search-tool hypothesis instead of reopening per tool call.
4. Done: isolate JSON-store indexing-eval artifacts by hypothesis and run id.
5. Done: delete dead `indexing_hypothesis_prompt` from `cli.py`.

### Medium Changes Under 1 Week

1. Add BM25/sparse lexical index.
2. Add Qdrant payload fields and filters.
3. Add query-aware graph expansion profiles.
4. Add typed code items for routes, commands, configs, tests, and workflows.
5. Add LLM reranker over top-N candidates with optional controlled reads.
6. Add case-level parallel evaluation with provider rate limits.

### Larger Bets

1. Tree-sitter or LSP-backed multi-language symbol graph.
2. SCIP import/reference index for languages with mature tooling.
3. Multi-vector Qdrant collections: code body, signature, docstring/summary, path/symbol.
4. AI-generated item summaries/tags over deterministic base items.
5. Answer-level evaluation with citations and source evidence checking.

## Bugs And Correctness Risks

| Severity | Risk | Evidence | Proposal |
| --- | --- | --- | --- |
| High | Open-ended search-tool loops are too expensive and unstable. | `DirectSearchOrchestrator.MAX_ROUNDS=5`; `rg_only` produced 6 errors on 10 cases. | Add one-shot candidate/rerank mode and make it default. |
| Fixed | JSON-backed indexing evals were not isolated by hypothesis. | `config_for_indexing_hypothesis` originally suffixed Qdrant collection and graph artifact, but not `config.artifact`. | Fixed in `d6abef1`; JSON artifacts are now suffixed per `<hypothesis>_<run_id>` and covered by tests. |
| High | AI-selected indexing undercovers the repo. | `ai_index_inspect_only` indexed 7 items and scored `hit@10=0.0`. | Use deterministic base index; AI only annotates or augments. |
| Medium | Graph expansion is query-agnostic. | Static weights in `GraphRetrievalStrategy`; edge kinds are not interpreted by query type. | Add graph traversal profiles and stage metrics. |
| Medium | Qdrant search cannot filter/rank by structured metadata. | Store payload keeps most metadata inside serialized `CodeItem`. | Promote payload fields and add indexes. |
| Fixed | `code_diver_search` reopened vector store/provider per tool call. | Historical `make_search_tool_handler` constructed both inside the nested handler. | Fixed in `d6abef1`; eval now injects a per-hypothesis retrieval strategy and closes once. |
| Medium | Vertex embedding path is serial per text. | `VertexEmbeddingProvider.embed_documents` loops one text at a time. | Batch or parallelize with rate limits. |
| Fixed | Cost reporting was model-agnostic. | Historical `ModelCostEstimator` used flat pricing independent of `result.model`. | Fixed in `d6abef1` with model-aware pricing and tests; move the table to YAML later. |
| Medium | CLI command handlers own too much application logic. | `cli.py` constructs providers/stores and runs eval loops. | Extract services and command objects. |
| Low | `rg` confidence is match-count heuristic. | `RgService._candidates` computes confidence only from count. | Add query term coverage, path/kind boosts, and exact-symbol boosts. |

## Next Five Commits

1. Correctness patch: isolate JSON-store indexing artifacts, reuse vector store/provider per search-tool hypothesis, and make cost estimates model-aware.
2. Refactor: extract `SearchToolEvaluationService` and `IndexingHypothesisRunner` from `cli.py` without behavior changes.
3. Implement normalized `Candidate` domain model and `HybridCandidateService` combining vector + lexical/path/symbol signals.
4. Add one-shot LLM rerank mode and an `ai_search_hybrid_rerank` hypothesis.
5. Add per-stage metrics, task-type metrics, and Qdrant payload indexes/filters.

## New Hypotheses To Test Next

These are intentionally narrower than the previous mixed toolsets:

| Hypothesis | Tools | Goal |
| --- | --- | --- |
| `ai_search_vector_rg` | `search`, `rg` | Test whether regex probes add recall when vector candidates are already available. |
| `ai_search_vector_symbols` | `search`, `symbols` | Test whether symbol inventory helps rank CLI/service entrypoints without source reads. |
| `ai_search_vector_inspect` | `search`, `inspect` | Test whether the composite inspect tool helps when anchored by vector candidates. |
| `ai_search_vector_rg_read` | `search`, `rg`, `read` | Test controlled source reads after vector and regex candidate generation. |
| `ai_search_vector_symbols_read` | `search`, `symbols`, `read` | Test whether symbol-guided reads beat raw regex-guided reads. |

Recommended run order on the 10-case smoke dataset:

```bash
uv run code-diver --config configs/protogen-ollama-qdrant.yml evaluate-search-tools --dataset datasets/protogen_eval.jsonl --hypothesis ai_search_vector_rg --hypothesis ai_search_vector_symbols --json
uv run code-diver --config configs/protogen-ollama-qdrant.yml evaluate-search-tools --dataset datasets/protogen_eval.jsonl --hypothesis ai_search_vector_inspect --json
uv run code-diver --config configs/protogen-ollama-qdrant.yml evaluate-search-tools --dataset datasets/protogen_eval.jsonl --hypothesis ai_search_vector_rg_read --hypothesis ai_search_vector_symbols_read --json
```

Promote only hypotheses that beat `ai_search_vector_only` on either `hit@10` or `mrr@10` without exceeding its token budget by more than 2x. If none do, move directly to deterministic hybrid candidate generation plus one-shot reranking.

## New Hypotheses Run Result

Executed on 2026-05-30 with run id `a5210403d9b6`; control repeat run id `6b87e3eef745`.

| Hypothesis | Tools | Hit@10 | MRR@10 | Tokens | Time | Errors | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ai_search_vector_only` | `search` | 1.00 | 0.867 | 28.7k | 45.8s | 0 | Keep as current control. |
| `ai_search_vector_rg` | `search`, `rg` | 0.40 | 0.400 | 66.1k | 140.3s | 5 | Reject. Regex exploration hurt quality and latency. |
| `ai_search_vector_symbols` | `search`, `symbols` | 0.70 | 0.700 | 59.9k | 131.9s | 3 | Reject as default. Symbol inventory may be useful as deterministic signal, not as an agent tool. |
| `ai_search_vector_inspect` | `search`, `inspect` | 0.60 | 0.600 | 93.9k | 105.5s | 3 | Reject as default. Composite inspection is too broad for open-ended loops. |
| `ai_search_vector_rg_read` | `search`, `rg`, `read` | 0.30 | 0.300 | 119.6k | 109.3s | 6 | Reject. Worst balance of quality, tool calls, and failures. |
| `ai_search_vector_symbols_read` | `search`, `symbols`, `read` | 0.60 | 0.600 | 98.1k | 90.3s | 3 | Reject as default. Reads should be controlled verification, not exploratory search. |

The tested hybrids show that simply giving the orchestrator more tools is the wrong default. The useful pieces are still valuable, but they should be combined below the agent boundary:

1. Deterministic candidate service: vector + lexical + path + symbol + graph signals merged into one ranked schema.
2. One LLM rerank turn over top candidates with a strict token budget.
3. Optional verification reads for the top 3 to 5 ranges only.
4. Per-stage metrics so vector, lexical, graph, rerank, and read costs are visible separately.

Next hypotheses:

| Hypothesis | Shape | Expected benefit |
| --- | --- | --- |
| `hybrid_candidates_no_llm` | Deterministic vector + lexical/path/symbol fusion. | Better recall than vector-only with near-zero token cost. |
| `hybrid_candidates_graph_boost` | Fusion plus query-aware AST/import/call graph boosts. | Better workflow and architecture queries. |
| `hybrid_candidates_rerank_once` | Fusion plus one Gemini rerank turn. | Better MRR without multi-round search cost. |
| `hybrid_candidates_verify_top3` | Fusion + rerank + bounded reads for top 3. | Better precision and answer evidence with controlled token growth. |
| `adaptive_identifier_fast_path` | Detect identifier/path queries and use lexical/symbol search before vectors. | Faster exact-code lookups. |

## Deterministic Hybrid Follow-Up

Executed on 2026-05-31 against `datasets/protogen_eval_100.jsonl`.

What changed:

- Added `hybrid` retrieval strategy with configurable vector, lexical, path, symbol, and graph weights.
- Added hypothesis-level `hybrid_search` YAML overrides, so experiments can compare weight profiles without code edits.
- Added cached item token profiles and an inverted lexical index.
- Fixed stale GraphRAG artifacts by preserving vector seed results even if the graph artifact does not contain the seed ids.
- Cached graph adjacency in `GraphRetrievalStrategy`.
- Made broad reference edges and AST call edges separately configurable.

Result:

| Strategy | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Mean/query | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `vector_qdrant` | 0.89 | 0.723 | 0.405 | 0.855 | 29ms | Keep as speed control. |
| `graph_ast_qdrant` | 0.89 | 0.723 | 0.405 | 0.855 | 30ms | Keep as graph infrastructure check; current edges do not improve ranking. |
| `hybrid_candidates_no_llm` | 0.90 | 0.734 | 0.448 | 0.865 | 78ms | Best quality/cost profile so far. |
| `hybrid_candidates_graph_boost` | 0.90 | 0.734 | 0.469 | 0.865 | 80ms | Best precision among high-hit profiles. |

Important finding: deterministic hybrid fusion achieved the improvement the agent-controlled tool hybrids did not. The gain is small, but it costs zero model tokens and avoids multi-round orchestration failures.

Performance finding: fresh indexing exposed expensive graph construction stages. Broad reference edges and AST call edges are now disabled in `configs/protogen-ollama-qdrant.yml`; they need bounded/incremental builders before they are safe for default indexing.

Next implementation hypotheses:

| Hypothesis | Change | Why |
| --- | --- | --- |
| Persist lexical index | Store token postings in artifact or Qdrant payload/sparse vectors. | Remove first-query hybrid warmup cost. |
| Query-aware graph profiles | Select graph edge kinds based on query intent. | Current graph edges do not improve ranking. |
| One-shot reranker | Run Gemini once over top 20 hybrid candidates. | Test whether MRR improves without open-ended loops. |
| Bounded verification reads | Read top 3 candidate ranges after rerank. | Improve final answer evidence without exploratory reads. |
| Incremental call graph | Build AST call edges per changed file or with hard time budgets. | Restore useful call edges without blocking indexing. |
