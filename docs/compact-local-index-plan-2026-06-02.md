# Compact Local Index Plan

Date: 2026-06-02

## Goal

Keep the persistent repository index small enough to stay hot in memory while preserving search quality:

- target persistent footprint: 1-3 GB;
- local embeddings only for retrieval/indexing;
- API LLM only for orchestration, tool selection, and final ranking;
- search should return likely files/symbols first, then read or grep code on demand.

## Hypothesis H1: File-Locator Index

Index the route to the answer, not the code body.

Persistent items:

- one `file_summary` vector per file;
- path, extension, imports, top symbols, and short file head;
- no line chunks;
- no method bodies;
- optional graph edges between file summaries.

The LLM receives candidate files and uses read/grep tools for exact evidence.

Early IntelliJ estimate:

- files: 74,906;
- vectors: 74,906;
- payload text: 172.95 MB;
- raw 768-dim vectors: 230.11 MB;
- observed Qdrant storage with Gemini API embedding control: 378 MB;
- observed graph JSON: 248 MB;
- observed persistent locator footprint: about 626 MB before process/RAM overhead.

First 1k-case IntelliJ control results on this index:

| Search profile | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | NDCG@10 | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Weighted hybrid baseline | 0.729 | 0.837 | 0.862 | 0.898 | 0.789 | 0.815 | 2.55 s |
| RRF | 0.691 | 0.825 | 0.847 | 0.900 | 0.764 | 0.797 | 2.57 s |
| Lexical-heavy hybrid | 0.744 | 0.848 | 0.872 | 0.906 | 0.801 | 0.826 | 2.82 s |

The important signal is that a search profile change beat the baseline without increasing index size. This supports testing several searchers and rankers against the same compact locator before making the persistent index larger.

## Hypothesis H1b: File Plus Signature-Symbol Locator

Add separate signature-only symbol vectors to improve symbol and workflow queries without storing code bodies.

Persistent items:

- `file_summary` items;
- `symbol` items containing kind, name, signature, and line range;
- no symbol body;
- no structural or line chunks.

Early IntelliJ estimate:

- files: 74,906;
- vectors/items: 523,137;
- payload text: 215.66 MB;
- raw 768-dim vectors: 1.61 GB.

This should still fit the 1-3 GB target, but build time and vector RAM are much higher than H1.

## Hypothesis H2: Ephemeral Deep Index

Use H1/H1b to find 20-50 candidate files. Then choose one of two branches:

1. `locator -> rg/read -> API LLM rank`
   - cheapest;
   - no temporary embeddings;
   - best when lexical evidence is strong.

2. `locator -> temporary chunk index over candidate files -> local vector search -> API LLM rank`
   - useful for vague semantic queries;
   - requires hot local embedder;
   - should measure `ephemeral_index_ms`, `temporary_vectors`, `rerank_ms`, and `total_ms`.

The second branch is only viable with local embeddings. API embeddings make per-query temporary indexing too slow and too expensive.

The H2 benchmark must freeze the locator candidate files before comparing branches. Otherwise the result mixes locator quality with second-stage quality. The fixed pool for the next run is `top_30_files` from the best locator profile, persisted per eval case.

Controlled H2 branches:

| Branch | Allowed scope | Model role | What it answers |
| --- | --- | --- | --- |
| Bounded grep/read | Only the top-N locator files. Max 3 grep/rg probes and max 8 reads. | The LLM proposes exact probes and ranks structured evidence. | Does direct code inspection beat another vector pass? |
| Ephemeral local vectors | Only the same top-N locator files. Build temporary syntax-aware chunks, embed locally, cache briefly. | The LLM may issue multiple semantic subqueries and rerank returned code chunks. | Does localized vectorization add quality beyond file-level locator? |

Bounded grep/read must not expose only raw regex. Short model-generated patterns are fragile against multiline signatures and optional parameters. The branch should offer structured file tools:

- `file_outline(path)`: classes, functions, methods, line ranges, imports, and top-level constants;
- `symbol_definition(path, symbol_or_terms)`: fuzzy lookup over symbols in the candidate file;
- `bounded_rg(files, pattern, mode)`: literal/regex search over the fixed candidate pool;
- `read_range(path, start, end)`: targeted reads after outline/symbol lookup.

The orchestrator prompt should prefer `file_outline` or `symbol_definition` before reading code. It should use grep for exact literals, log fragments, annotations, config keys, and fallback keyword probes.

Ephemeral local vectors must embed syntax-aware chunk text with a breadcrumb header:

```text
[file: src/foo/UserController.kt] -> [class: UserController] -> [function: updateUser]
<function body or structural chunk>
```

The breadcrumb is part of the embedded text and the returned evidence payload. Without it, function-level vectors can become detached from ownership and the LLM may rank the right behavior under the wrong file.

The primary comparison is not global Hit@10. It is conditional quality after the locator has already found the right file:

- `locator_hit@20/50`;
- gold-file rank before H2;
- final Hit@1/3/5;
- rank delta after H2;
- grep/read calls;
- temporary vector count;
- `ephemeral_build_ms`: parser + chunk creation + embedding + temporary index write;
- `ephemeral_query_ms`: vector search over an already-warm temporary index;
- `ephemeral_cache_hit_rate`;
- rerank tokens/cost;
- bucket split: exact/path/symbol vs semantic/workflow.

Build time and query time must be reported separately. For quality analysis, compare final Hit/MRR using the same fixed top-30 pool and a warm embedding runtime. Cache optimization, incremental IDE updates, and temporary-index reuse are a later performance step.

Expected pattern:

- exact names, log fragments, config keys: bounded grep/read should win;
- vague behavioral queries: ephemeral local vectors plus rerank should win;
- if neither wins over locator + simple rerank, H2 is not worth the complexity.

## API Model Role

The API LLM should not be the embedding provider in the target design. It should:

- rewrite the user query into several search intents;
- call locator/vector/BM25/path/symbol/graph tools in parallel where useful;
- inspect top candidates with targeted `rg`/read calls;
- optionally request an ephemeral deep index for candidate files;
- rerank structured evidence;
- return files/symbols/line ranges with confidence.

Current model matrix to test:

| Embeddings | Ranker/orchestrator | Runtime |
| --- | --- | --- |
| Qwen3-Embedding 0.6B | Qwen3.5 4B | vLLM/MLX embeddings + local OpenAI-compatible generation |
| Qwen3-Embedding 0.6B | Gemini 3.1 Flash-Lite | vLLM/MLX embeddings + Vertex/Gemini |
| Qwen3-Embedding 0.6B | Gemini 3.5 Flash | vLLM/MLX embeddings + Vertex/Gemini |
| Qwen3-Embedding 4B | Qwen3.5 4B | vLLM/MLX embeddings + local OpenAI-compatible generation |
| Qwen3-Embedding 4B | Gemini 3.1 Flash-Lite | vLLM/MLX embeddings + Vertex/Gemini |
| Qwen3-Embedding 4B | Gemini 3.5 Flash | vLLM/MLX embeddings + Vertex/Gemini |

Ollama is not part of the target runtime. Historical Ollama-named artifacts are kept only as past benchmark records. New local embedding runs should use vLLM/MLX OpenAI-compatible `/v1/embeddings`; local dedicated rerank should use llama.cpp `/v1/rerank`.

## TUI Direction

Build the TUI as a thin live view over JSONL trace events, not as retrieval logic.

Panels:

- run header: config, repo, index, model, elapsed, cost;
- indexing progress: files scanned, items, batches, vectors/sec, index size;
- search timeline: LLM reasoning step, tool calls, parallel groups, retries;
- candidate table: file, rank, score, signal breakdown, confidence;
- rank diff: vector rank -> hybrid rank -> LLM rank;
- evidence preview: path, lines, snippets;
- metrics footer: hit@k, precision/recall, latency, token/cost counters.

Recommended stack:

- Textual for full TUI;
- Rich for colored logs and tables in non-interactive mode;
- JSONL traces as the event contract.

## Required Metrics

- `index_items`;
- `index_vector_mb_estimate`;
- `qdrant_storage_mb`;
- `graph_artifact_mb`;
- `locator_hit@k`;
- `file_recall@k`;
- `candidate_files`;
- `grep_calls`;
- `read_calls`;
- `ephemeral_index_ms`;
- `ephemeral_vectors`;
- `rerank_ms`;
- `total_ms`;
- `api_input_tokens`;
- `api_output_tokens`;
- `api_cost_usd`.
