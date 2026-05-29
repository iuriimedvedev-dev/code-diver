# Codebase RAG Research Notes

Goal: reduce tokens, keep answer quality, and make repository retrieval fast and precise.

## Current State After Baseline Runs

The current implementation is intentionally inspectable, but it is still a baseline:

- `CodebaseScanner` walks files, filters by suffix/glob, and chunks by fixed line windows.
- The container protogen config currently uses `embedding.provider: hash`, so those metrics measure a fast lexical-ish baseline, not Gemini/Ollama/OpenAI semantic embeddings.
- `indexing.mode: scanner` means the container baseline does not ask the AI orchestrator to plan the index.
- `indexing.mode: orchestrated` asks the generation provider for include/exclude/chunk sizing from repo tree, aggregate stats, and sample paths only. It does not send source contents to the model.
- Indexing traces are now first-class config via `trace.*`; JSONL trace includes AI index prompt/response/selected plan, selected scanner config, item counts, embedding concurrency, provider/model/dimensions, and vector counts.
- Deterministic GraphRAG now includes same-file, bounded import, lexical reference, containment, and Python AST call edges. Import edges are bounded to file representatives so imports do not explode across every chunk pair.
- Gemini defaults now use `gemini-3.5-flash` for orchestration and `gemini-embedding-2` for embeddings. The embedding provider handles Embedding 2's no-`task_type` contract and creates separate `Content` objects for batch document embeddings.

This explains the weak metrics: we are measuring line-window chunks and a hash embedding baseline against repo-level questions. That is useful as a control group, but not a competitive code RAG system.

## Experiment Results on `../protogen`

Dataset: `datasets/protogen_eval.jsonl`, 10 repository-location cases, `limit=10`.

| Config | Indexing | Items | Strategy | Hit@10 | MRR@10 | Notes |
| --- | --- | ---: | --- | ---: | ---: | --- |
| `configs/protogen-baseline.yml` | line chunks, hash embeddings | 2444 | vector | 0.70 | 0.372 | Best current cheap baseline. |
| `configs/protogen-baseline.yml` | line chunks, hash embeddings | 2444 | recursive | 0.50 | 0.256 | More latency, worse hit rate. |
| `configs/protogen-baseline.yml` | line chunks, hash embeddings | 2444 | graph | 0.60 | 0.359 | Import/same-file graph helps some cases. |
| `configs/protogen-symbols.yml` | symbol-only during first run, hash embeddings | 6961 | vector | 0.30 | 0.144 | Bad: tiny method chunks lost file-level context. |
| `configs/protogen-symbols.yml` | hybrid line+symbol chunks, hash embeddings | 8842 | vector | 0.30 | 0.250 | Better MRR than symbol-only, still worse than baseline. |
| `configs/protogen-symbols.yml` | hybrid line+symbol chunks, hash embeddings | 8842 | recursive | 0.50 | 0.298 | Best recursive run so far, still below baseline vector hit rate. |
| `configs/protogen-symbols.yml` | hybrid line+symbol chunks, hash embeddings | 8842 | graph | 0.30 | 0.250 | Reference graph needs better reranking. |
| `configs/protogen-orchestrated-hash.yml` | Gemini index plan + symbol replacement, hash embeddings | 6975 | orchestrated | 0.40 | 0.242 | Query planning worked, but symbol replacement hurt. |
| `configs/protogen-symbols.yml` | hybrid line+symbol + AST graph, hash embeddings | 8842 | vector | 0.30 | 0.250 | Control after AST graph change; unchanged. |
| `configs/protogen-symbols.yml` | hybrid line+symbol + AST graph, hash embeddings | 8842 | recursive | 0.50 | 0.298 | Still the best hash run. |
| `configs/protogen-symbols.yml` | hybrid line+symbol + AST graph, hash embeddings | 8842 | graph | 0.30 | 0.220 | Faster after bounded imports, but quality still needs rerank/path boosts. |
| `configs/protogen-ollama-embeddings.yml` | local mxbai-embed-large + hybrid line/symbol/AST graph | 8246 | vector | 0.90 | 0.663 | Best measured retrieval quality; JSON vector store is still slow. |
| `configs/protogen-ollama-embeddings.yml` | local mxbai-embed-large + hybrid line/symbol/AST graph | 8246 | recursive | 0.90 | 0.612 | More latency without quality gain over vector. |
| `configs/protogen-ollama-embeddings.yml` | local mxbai-embed-large + hybrid line/symbol/AST graph | 8246 | graph | 0.90 | 0.663 | Same quality as vector in this run; graph expansion did not improve ranking yet. |
| `configs/protogen-ollama-qdrant.yml` | local mxbai-embed-large + embedded Qdrant | 8246 | vector | 0.90 | 0.663 | Same quality as JSON, 0.4s eval instead of 14.4s. |
| `configs/protogen-ollama-qdrant.yml` | local mxbai-embed-large + embedded Qdrant | 8246 | recursive | 0.90 | 0.612 | 1.4s eval instead of 57.9s. |
| `configs/protogen-ollama-qdrant.yml` | local mxbai-embed-large + embedded Qdrant | 8246 | graph | 0.90 | 0.663 | 3.8s eval; graph expansion still not improving ranking. |
| `configs/protogen-vertex-smoke.yml` | Vertex gemini-embedding-2 selected-file smoke index | 603 | vector | 0.70 | 0.700 | End-to-end Vertex provider works through ADC; not comparable to full-repo runs. |

Important trace findings:

- The first AI index plan replaced source include patterns with broad eval/tooling patterns, producing only 371 indexed items and `hit@10=0.10`. The trace made the failure obvious.
- Include patterns from AI are now additive and guarded. Hidden/tool-state additions are rejected, and broad additions that match too many files are rejected.
- Gemini consistently prefers `symbol_chunks=true` for this repo. With hash embeddings, symbol granularity alone is not enough; we need hybrid retrieval and reranking.
- A live `gemini-3.5-flash` orchestration smoke reached the API but hit capacity/deadline errors; the configured fallback chain returned JSON successfully. `gemini-embedding-2` returned 768-dimensional document and query vectors.
- Vertex provider was implemented with the current `google-genai` Vertex path. `GEMINI_API_KEY` is valid for Gemini Developer API but not accepted by Vertex `aiplatform.googleapis.com`; refreshed ADC works. Vertex generation smoke returned JSON in about 2.7s, and Vertex embedding smoke returned 768-dimensional vectors in about 1.6s.
- Full Vertex indexing was stopped after the planner succeeded because embedding 8842 items would take too long with the current one-content-per-request Vertex embedding path. A bounded Vertex smoke index over 603 items completed and produced `hit@10=0.70`, `MRR@10=0.70`.
- A live orchestrated evaluation loop exposed latency risk: query-plan calls on `gemini-3.5-flash` sometimes took 40-50 seconds. We added a 20s generation timeout guard; evaluation should not depend on unbounded live orchestration.
- AST GraphRAG initially produced 671,857 edges and a 177MB graph artifact because imports linked every source chunk to every imported target chunk. Bounded import representatives reduced this to 161,681 edges and a 60MB graph artifact.
- Local Ollama `mxbai-embed-large` embeddings are currently the best measured option on this dataset. Moving them from JSON brute-force search to embedded Qdrant preserved quality and reduced vector evaluation from 14.4s to 0.4s.
- The next useful hypothesis is not "symbols vs chunks"; it is "file chunks + symbols + lexical/path boosts + rerank".

## Current Design Hypotheses

### H1: Recursive AI Search

Single-shot vector search is cheap, but it fixes the context set too early. Recursive search should improve precision for ambiguous questions by:

- running a first semantic search;
- deriving follow-up subqueries from the best results;
- merging and deduplicating evidence;
- stopping after a small configured number of rounds.

This follows the broader agentic retrieval pattern: a reasoning model or harness uses search/open/find tools iteratively instead of trusting one top-k retrieval pass. Microsoft’s AgenticRAG reports that moving from single-shot retrieval to agentic tool use was the most significant quality factor in its ablations, while multi-query search and in-document navigation also helped efficiency.

Implementation in this repo:

- `search.strategy: recursive`
- `recursive_search.rounds`
- `recursive_search.branch_limit`
- `recursive_search.limit`

### H2: GraphRAG for Codebase Indexation

Vector search captures topical similarity, but code questions often need dependency chains: controller -> service -> repository, interface -> implementation, caller -> callee, import -> module. A deterministic code graph should preserve these relationships without paying LLM indexing costs.

Initial graph shape:

- nodes: indexed `CodeItem`s;
- edges: same-file adjacency, bounded imports, lexical references, containment, and Python AST calls;
- retrieval: vector seeds first, then bounded graph expansion.

This is deliberately cheap and deterministic. The next quality step should be AST/LSP/SCIP edges, not LLM-extracted knowledge graphs.

Implementation in this repo:

- `search.strategy: graph`
- `graph.artifact`
- `graph.ast_enabled`
- `graph.expansion_depth`
- `graph.neighbor_limit`

## Existing Approaches

### Vector Code Search

Qdrant’s semantic code search tutorial recommends indexing code structures rather than arbitrary chunks: functions, class methods, structs, enums, signatures, docstrings, comments, and location metadata. It also recommends using both natural-language text representations and code-specific embeddings, then merging results when they retrieve complementary snippets.

Useful takeaway: our current line-window chunker is a baseline. For quality, we should move toward semantic code items and richer metadata.

Source:

- https://qdrant.tech/documentation/advanced-tutorials/code-search/

### Qdrant as Vector Store

Qdrant supports dense vector search, payload filtering, hybrid queries, sparse vectors, multivectors, reranking, and local/embedded modes. For this sandbox we added:

- JSON vector store for deterministic local tests;
- Qdrant vector store for realistic low-latency retrieval experiments;
- embedded `location: ":memory:"` support for tests.

Sources:

- https://qdrant.tech/documentation/
- https://github.com/qdrant/qdrant

### Code Intelligence Graphs

Sourcegraph separates search-based code navigation from precise code navigation. Search-based navigation uses text search and syntax heuristics for broad coverage; precise navigation relies on compile/build-aware indexes such as SCIP to power go-to-definition, references, implementations, and cross-repository relationships.

Useful takeaway: our graph should evolve from regex/import heuristics to SCIP/LSP/tree-sitter-backed symbol edges.

Sources:

- https://sourcegraph.com/docs/code-navigation
- https://sourcegraph.com/docs/code-navigation/precise-code-navigation
- https://sourcegraph.com/docs/code-navigation/writing-an-indexer

### GraphRAG for Code

Recent codebase GraphRAG research reports that vector-only retrieval fails on multi-hop architecture questions. A 2026 benchmark compared vector-only RAG, LLM-extracted knowledge graphs, and deterministic AST-derived graphs; the deterministic AST graph had better coverage, lower indexing cost, and the best correctness on the tested Java codebases.

Useful takeaway: do not start with LLM-generated graphs. Build deterministic AST/import/symbol graphs first, then optionally enrich.

Source:

- https://arxiv.org/abs/2601.08773

RepoGraph treats a repository-level code graph as navigation infrastructure for AI software engineering systems and reports gains when plugged into SWE-bench-oriented agents. GraphCodeAgent builds both a requirement graph and a structural-semantic code graph, then uses multi-hop agent reasoning to retrieve explicit and implicit code snippets for repo-level generation.

Sources:

- https://arxiv.org/abs/2410.14684
- https://arxiv.org/abs/2504.10046

CodeRAG-Bench shows that code retrievers still struggle when relevant context has weak lexical overlap with the query, which matches the failure mode seen in our hash/vector baseline. RealBench, published in 2026, reinforces that repo-level work should be evaluated with realistic repository tasks rather than only small natural-language coding prompts.

Sources:

- https://arxiv.org/abs/2406.14497
- https://arxiv.org/abs/2604.22659

### Cost-Efficient Graph Retrieval

Clue-RAG uses a multi-partite graph over chunks, knowledge units, and entities, plus query-driven iterative retrieval. It reports improved accuracy/F1 while reducing indexing costs and can match or beat baselines without LLM indexing.

Useful takeaway: our graph should support multiple node granularities later: file, symbol, chunk, test, dependency, and possibly generated summary.

Source:

- https://arxiv.org/abs/2507.08445

### General GraphRAG Lessons

Microsoft GraphRAG's indexing pipeline extracts entities, relationships, and claims, performs community detection, creates summaries, and stores both graph tables and vector embeddings. The important lesson for code is architectural, not literal: keep indexing configurable, persist intermediate artifacts, and trace expensive extraction decisions. For source code, deterministic AST/LSP/tree-sitter extraction should come before LLM graph extraction.

Sources:

- https://microsoft.github.io/graphrag//index/overview/
- https://github.com/microsoft/graphrag

## Near-Term Experiment Plan

1. Baseline vector search
   - Current `search.strategy: vector`.
   - Measure hit rate, MRR, recall, latency, indexed items, and context token estimate.

2. Recursive search
   - Current `search.strategy: recursive`.
   - Compare quality gain vs extra queries and latency.
   - Tune rounds and branch limits to avoid token/query explosion.

3. Deterministic GraphRAG
   - Current `search.strategy: graph`.
   - Start with import and same-file expansion.
   - Add AST symbol edges next: defines, calls, references, inherits, implements, tests.
   - Store file, symbol, chunk, and dependency nodes separately instead of treating every chunk as one flat item type.
   - Add a bounded graph traversal trace so each query explains why neighbors were pulled.

4. Qdrant backend
   - Switch `storage.provider: qdrant`.
   - Test local embedded store, then server-backed Qdrant.
   - Add payload filters by language, path, item kind, and repository.

5. Evaluation dataset growth
   - Add task types:
     - locate implementation;
     - trace call chain;
     - explain architecture;
     - find tests;
     - identify change impact.
   - Track metrics per task type, not only aggregate.

6. Hybrid retrieval and reranking
   - Combine `rg`/literal hits, semantic vector search, path/symbol filters, and graph expansion.
   - Rerank with a small top-N cross-encoder/LLM pass only after cheap retrieval narrows candidates.
   - Track latency, token cost, candidate count, context tokens, and answer correctness per stage.

## Design Bias

- Prefer deterministic indexing over LLM indexing.
- Use LLM/agent work at query time only when it buys measurable quality.
- Keep retrieval artifacts inspectable and reproducible.
- Make all expensive knobs configurable in YAML.
- Optimize for bounded context, not maximal context.
