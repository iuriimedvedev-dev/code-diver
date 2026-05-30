# Optimization Audit

Date: 2026-05-30

## Claude Code Audit Status

Requested command: run Claude Code CLI with `claude-opus-4-8` for a long read-only audit.

Local Claude Code is installed (`2.1.112`) and supports the needed flags: `--model`, `--effort`, `--allowedTools`, `--disallowedTools`, and `--output-format json`.

The external Claude run was blocked by the execution policy because it would transmit private repository contents to Anthropic. The attempted command used read-only tools and explicitly disallowed edit/write tools, but policy still rejected the external disclosure. This report is therefore a local audit by Codex plus web research, not a Claude-generated audit.

## Executive Summary

The current system already has the right experimental shape: config-first CLI, Qdrant, reproducible datasets, trace logs, direct provider orchestration, and isolated tool hypotheses. The strongest measured path is also clear: expose a structured vector candidate tool to the model, not raw `rg` as the primary search loop.

Highest-leverage optimizations:

1. Replace open-ended multi-round search with a two-stage pipeline: cheap candidate generation first, one bounded LLM rerank/answer turn second.
2. Add hybrid retrieval: vector + BM25/sparse lexical + path/symbol boosts + graph signals.
3. Make GraphRAG deterministic and query-aware: AST/LSP/tree-sitter graph edges first, bounded traversal second, LLM graph extraction last if ever.
4. Replace fixed line-window chunks with typed, multi-granularity code items: file summaries, symbols, routes/commands/configs, tests, and chunk windows.
5. Move the eval harness out of `cli.py` into services so experiments are easier to parallelize, persist, and test.

The latest 10-case live eval strongly supports this direction:

| Hypothesis | Hit@10 | MRR@10 | Tokens | Duration | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| `ai_search_vector_only` | 1.00 | 0.867 | 32.1k | 53.6s | 0 |
| `ai_search_rg_only` | 0.30 | 0.300 | 134.9k | 134.8s | 6 |
| `ai_search_vector_read` | 0.80 | 0.800 | 110.0k | 113.4s | 1 |
| `ai_search_rg_read` | 0.40 | 0.400 | 279.8k | 116.2s | 2 |

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
5. Full trace prompts are useful for audits but expensive if replayed into subsequent prompts.

Evidence:

- Search-tool eval loops cases serially in `src/code_diver/cli.py:488`.
- The orchestrator itself runs each case as a model/tool loop in `src/code_diver/agent/direct_search_orchestrator.py:68`.
- Vertex document embeddings call the parent provider once per text in `src/code_diver/providers/vertex_embedding_provider.py:48`.

Proposals:

- Add `--workers` to `evaluate-search-tools` for case-level parallelism when providers allow it.
- Add hard prompt-history budget in tokens, not only JSON character compression.
- Add one-shot rerank mode with max one generation call per case.
- Add provider-level rate limiter and retry policy with backoff/jitter.
- Batch Vertex embeddings if the SDK/API path supports it; if not, document expected time and expose higher safe concurrency.

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
3. Cost estimates are model-name based and can drift.
4. Vertex auth is ADC/project/location based; AI Studio API keys are not Vertex credentials.
5. OpenAI-compatible local embedding paths should be treated as local provider profiles, not as OpenAI proper.

Proposals:

- Add `code-diver doctor providers` to smoke generation and embeddings for each configured provider.
- Persist provider/model/version/dimensions in every run row and report.
- Add a model registry config with pricing and capabilities rather than hardcoding in cost estimator.
- Add provider-specific timeout/retry/rate-limit config.

## Concrete Implementation Plan

### Quick Wins Under 1 Day

1. Extract eval loops from `cli.py` into services.
2. Add isolated `hybrid_candidates` tool that calls vector + lexical and returns one normalized candidate list.
3. Add per-stage timing and candidate counts to `evaluate-search-tools`.
4. Add task type field to `EvalCase` and dataset generator.
5. Add default one-shot `vector_candidates -> final results` agent mode.

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
| High | AI-selected indexing undercovers the repo. | `ai_index_inspect_only` indexed 7 items and scored `hit@10=0.0`. | Use deterministic base index; AI only annotates or augments. |
| Medium | Graph expansion is query-agnostic. | Static weights in `GraphRetrievalStrategy`; edge kinds are not interpreted by query type. | Add graph traversal profiles and stage metrics. |
| Medium | Qdrant search cannot filter/rank by structured metadata. | Store payload keeps most metadata inside serialized `CodeItem`. | Promote payload fields and add indexes. |
| Medium | Vertex embedding path is serial per text. | `VertexEmbeddingProvider.embed_documents` loops one text at a time. | Batch or parallelize with rate limits. |
| Medium | CLI command handlers own too much application logic. | `cli.py` constructs providers/stores and runs eval loops. | Extract services and command objects. |
| Low | `rg` confidence is match-count heuristic. | `RgService._candidates` computes confidence only from count. | Add query term coverage, path/kind boosts, and exact-symbol boosts. |

## Next Five Commits

1. Extract `SearchToolEvaluationService` and `IndexingHypothesisRunner` from `cli.py` without behavior changes.
2. Implement normalized `Candidate` domain model and `HybridCandidateService` combining vector + lexical/path/symbol signals.
3. Add one-shot LLM rerank mode and an `ai_search_hybrid_rerank` hypothesis.
4. Add per-stage metrics and task-type metrics to eval output and ClickHouse rows.
5. Add Qdrant payload indexes/filters plus payload fields for path, kind, language, symbol, start/end lines.
