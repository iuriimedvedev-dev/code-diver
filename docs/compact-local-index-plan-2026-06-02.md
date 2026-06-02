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

## API Model Role

The API LLM should not be the embedding provider in the target design. It should:

- rewrite the user query into several search intents;
- call locator/vector/BM25/path/symbol/graph tools in parallel where useful;
- inspect top candidates with targeted `rg`/read calls;
- optionally request an ephemeral deep index for candidate files;
- rerank structured evidence;
- return files/symbols/line ranges with confidence.

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
