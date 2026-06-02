# Explanation

This document is the plain-language map of what Code Diver is doing, why we test several search strategies, and where the current weak spots are.

## Big Picture

We have two separate phases:

1. **Index once.** Traverse a repository, build searchable representations, store them in Qdrant plus local artifacts.
2. **Search many times.** For each user query, generate candidates cheaply, then optionally ask an LLM to rerank or verify a short list.

The key rule: indexing quality defines the ceiling. If the right file is not present in the candidate set, no reranker can recover it.

## Current Direction: Small Hot Locator, Deep Search On Demand

For a large repository like IntelliJ, indexing every chunk of source code is the wrong default. It creates a second copy of the repository inside the vector DB, increases RAM/storage, and gives the reranker too many near-duplicate candidates.

The better shape is a two-layer system:

1. **Persistent locator index.** Keep a compact index hot in memory. Its job is to find likely files and entry-point symbols.
2. **On-demand deep search.** Once we have 20-50 candidate files, either grep/read them directly or build a temporary fine-grained index only for those files.

The persistent index should answer: "where should we look?" The exact code evidence should be read after that.

### H1: File-Locator Index

One vector per file. The indexed text contains path, extension, imports, top symbols, and a short file head. It does not store method bodies or line chunks.

Why this is attractive:

- small enough to keep hot;
- fast candidate generation;
- avoids repeated chunks from the same file;
- gives the LLM a clean list of files to inspect.

Current IntelliJ measurement:

| Metric | Value |
| --- | ---: |
| Files / vectors | 74,906 |
| Payload text | 172.95 MB |
| Raw vector estimate, 768 dims | 230.11 MB |
| Observed Qdrant storage | 378 MB |
| Graph JSON | 248 MB |
| Persistent locator footprint | about 626 MB before runtime overhead |
| Hit@1 on 1k IntelliJ control run | 0.729 |
| Hit@3 | 0.837 |
| Hit@5 | 0.862 |
| Hit@10 / file recall@10 | 0.898 |

This is already inside the target 1-3 GB class.

The same index should be searched with multiple search profiles. On the first 1k IntelliJ sweep, a lexical-heavy hybrid profile improved Hit@1 from `0.729` to `0.744` and Hit@10 from `0.898` to `0.906`. RRF was worse for Hit@1 (`0.691`) while keeping similar Hit@10 (`0.900`). This points to a practical rule: once locator recall is high enough, ranking and signal weighting matter more than adding more permanent chunks.

### H1b: File Plus Signature Symbols

Add separate symbol vectors, but keep them signature-only:

```text
symbol: method createUser
signature: public User createUser(...)
lines: 42-87
```

Do not store the body. The model can read the body later if this symbol becomes a candidate.

Current IntelliJ scan-only estimate:

| Metric | Value |
| --- | ---: |
| Files | 74,906 |
| Items / vectors | 523,137 |
| Payload text | 215.66 MB |
| Raw vector estimate, 768 dims | 1.61 GB |

This is still plausibly inside 1-3 GB, but the build cost and vector RAM are much higher than H1. It is a quality-vs-footprint hypothesis, not the default.

### H2: Temporary Deep Index Over Candidate Files

After H1/H1b returns candidate files, we have a fork:

| Branch | Flow | When it should win |
| --- | --- | --- |
| Grep/read branch | locator -> `rg`/read -> API LLM rank | Exact terms, config keys, class names, unique strings. |
| Ephemeral index branch | locator -> build temporary chunks over 20-50 files -> local vector search -> API LLM rank | Vague semantic queries where grep does not know what to search. |

The temporary index only makes sense with a hot local embedding model. API embeddings are too slow and too expensive for per-query indexing.

## Role Of Local Models And API Models

Embeddings should be local in the target system. We need them for:

- persistent locator indexing;
- query embedding;
- temporary per-candidate-file indexing;
- cheap repeated experiments.

The API LLM should not be the embedder. Its job is orchestration and ranking:

1. Read the user query.
2. Generate several search intents.
3. Call vector/path/symbol/BM25/graph tools, often in parallel.
4. Decide whether to use grep/read or temporary deep indexing.
5. Rank structured candidates.
6. Return files, line ranges, evidence, and confidence.

This keeps expensive tokens focused on reasoning and ranking, not brute-force retrieval.

## TUI Goal

The UI should make the search process inspectable:

- live indexing progress;
- current model/provider;
- vector batches/sec;
- Qdrant size and graph artifact size;
- tool calls grouped by parallel round;
- candidate table with scores and rank changes;
- token/cost/latency counters;
- final evidence and confidence.

Implementation direction: use JSONL trace events as the backend contract. Rich is already available for colored logs and live panels; a Textual app can come later.

## What We Index

The deterministic indexer builds several kinds of items:

| Index item | What it stores | Why it helps |
| --- | --- | --- |
| File summary | One compact representation of a file. | Good for broad questions like "where is auth handled?" |
| Code chunk | A bounded range of source text. | Good for local behavior that is not a class or method name. |
| Symbol | Class/function/method names with location metadata. | Strong for exact code navigation and API-like queries. |
| Structural chunk | AST-aware code ranges instead of arbitrary line windows. | Reduces cases where the useful unit is split across chunks. |
| Graph edge | Relationships like containment, imports, references, or call-like links. | Helps workflow questions where the answer is near another known symbol. |

Each item has metadata: path, line range where available, item kind, symbol name where available, and text prepared for embeddings.

## Why A Graph Is Not Enough By Itself

A graph can cover the codebase without making search precise. Coverage means the answer exists somewhere in the index. Search quality means the answer is ranked near the top for an informal human query.

The hard part is the gap between how developers ask questions and how code is represented:

| Problem | Example | Why it hurts |
| --- | --- | --- |
| Granularity | A whole file is too broad, a method is too narrow. | File embeddings blur several responsibilities; tiny method embeddings lose owner/context. |
| Node text quality | A node only says `class FooManager`. | The embedding model sees poor text, even if the AST node is structurally correct. |
| Edge semantics | `imports`, `calls`, `extends`, `registered_in`, and `test_for` are different. | Uniform graph expansion pulls noisy neighbors into the candidate pool. |
| Large-repo fanout | Core IntelliJ services have many imports/callers/extensions. | The graph can swamp the right file with plausible infrastructure files. |
| Query mismatch | "where is authorization handled?" may map to sessions, permissions, interceptors, tokens, or config. | The exact words may not exist near the owning code. |
| Ranking | The right file is rank 8 instead of rank 1. | The system technically found it, but still wastes context and user time. |
| Non-code ownership | Behavior can start in `plugin.xml`, Gradle, YAML, or service descriptors. | A pure Java/Kotlin AST graph misses important entry points. |

The better shape is a typed hierarchical graph, not only "nodes with embeddings": repository/module/file/symbol/config/chunk nodes, enriched node text, typed edges, route-specific traversal, and a reranker over the merged candidate set.

So the graph should be the skeleton of the index. It still needs good node descriptions and a ranking stage that understands the user's intent.

## What Embeddings Do

An embedding model converts text into a vector. We embed both repository items and user queries. Qdrant then finds items whose vectors are close to the query vector.

This is good when the query is informal:

```text
where is authorization handled?
```

It is weaker when the query depends on exact names, file paths, generated code conventions, or multi-step workflows. That is why vector search alone is not enough.

## Search Tools And Their Jobs

| Tool or signal | Job | Best cases | Failure mode |
| --- | --- | --- | --- |
| Vector search | Semantic candidate generation. | Informal intent, synonyms, broad concepts. | Can return plausible but wrong files. |
| BM25/lexical | Text overlap ranking. | Error messages, config keys, exact terms. | Misses synonyms and renamed concepts. |
| `rg`/grep | Exact repository scan. | Unique strings, class names, flags, annotations. | Bad for vague intent. |
| Path boost | Prefer files whose path matches the query. | "where is cli config" or "qdrant store". | Can over-rank coincidental path matches. |
| Symbol boost | Prefer class/function/method names. | "where is command created?" if names are explicit. | Misses behavior hidden in generic methods. |
| GraphRAG/AST expansion | Pull neighbors of plausible items. | Workflows, dispatch, factory/strategy relationships. | Graph edges can add noise if not reranked. |
| LLM rerank | Choose the best order from structured candidates. | Ambiguous top 20 where the right file is present. | Cannot fix missing candidates; local small LLMs can mis-rank. |
| Targeted read | Verify top 3-5 snippets after ranking. | Final answer confidence and citations. | Expensive if used before candidate narrowing. |

## Current Main Strategies

| Strategy | What happens | What it tests |
| --- | --- | --- |
| `hybrid_candidates_symbol_first` | Deterministic vector + lexical + path/symbol fusion. No LLM rerank. | Cheap candidate quality and raw embedding quality. |
| `hybrid_rerank_flash_lite_top20_compact` | Generate candidates, send compact top-20 table to the LLM, ask for JSON ordering. | Whether the LLM can improve rank without reading files. |
| `hybrid_rerank_flash_lite_file_first` | Group candidates by file, ask the LLM to choose owning files before detailed items. | Whether file-level reasoning improves Hit@1/Hit@3. |
| `hybrid_rerank_precision` | Prompt optimized for rank-one correctness. | Whether stricter instructions beat compact rerank. |
| `hybrid_rerank_base_prior` | Keep deterministic order stronger unless reranker has evidence. | Whether we can prevent LLM from demoting already-correct top results. |
| `hybrid_rerank_flash_lite_structural_file_first` | Use structural/AST candidates plus file-first rerank. | Whether better chunks help reranking. |
| Agentic search | Let the model call tools like search, symbols, grep, inspect, read, and rerank. | Whether multi-step tool use beats one bounded rerank call. |

So far, the bounded rerank path is more stable than open-ended agentic search. The agent can be useful for hard cases, but it needs strict budgets and structured tool outputs.

## What Happens During A Search

The intended high-quality flow is:

1. Receive the user query.
2. Classify it roughly: semantic, path/symbol, exact text, workflow, or mixed.
3. Run several cheap candidate generators in parallel: vector, lexical, path/symbol, graph expansion.
4. Merge and deduplicate candidates by file and item id.
5. Keep a candidate pool around top 20-40 for recall.
6. Ask a reranker to select a short list.
7. Inspect only top 3-5 ranges when verification is needed.
8. Return a readable answer with file paths and line numbers.

Top-10 is too wide for the final answer. It is useful as a candidate-recall metric, but for the real searcher we should optimize `hit_rate@3`, `hit_rate@5`, and `mrr@10`.

## Why Top-3 And Top-5 Matter

If `hit_rate@10` is high but `hit_rate@3` is low, the system "technically found" the file but buried it. That still burns context and makes the user experience bad.

The practical target is:

| Metric | Meaning |
| --- | --- |
| `hit_rate@1` | The first result is right. |
| `hit_rate@3` | A tiny verification pass can find the right file. |
| `hit_rate@5` | A realistic AI searcher can inspect a short list without wasting many reads. |
| `hit_rate@10` | Candidate generation did not completely miss the answer. |

So top-10 is not the product goal. Top-3/top-5 is.

## Should AI Also Index?

Yes, but not as a replacement for deterministic indexing.

A useful AI indexing pass should run after or alongside deterministic indexing and produce **evidence-linked memory notes**:

| AI memory item | Example | Guardrail |
| --- | --- | --- |
| Module responsibility | "`src/code_diver/agent` contains direct tool orchestration and reranking support." | Must cite files that support the note. |
| Workflow note | "Evaluation loads dataset cases, runs a retrieval strategy, then computes ranking metrics." | Must link to source paths and line ranges. |
| Synonym map | "auth/session/login may map to token/provider/client code." | Must be treated as a retrieval hint, not truth. |
| Architecture map | "Indexing builds items, storage persists vectors, retrieval ranks candidates." | Must be regenerated when index changes. |

This can improve informal queries because the model can write down project concepts in human language that may not appear literally in source code.

The risk is hallucination. Therefore AI memory notes must be stored as separate index items with source evidence. They should not overwrite deterministic facts.

## Where We May Be Missing Quality

1. Candidate recall and final ranking are mixed together. We need reports that say whether the gold file was absent from top 20 or present but mis-ranked.
2. We need stronger file-level voting before LLM rerank. Many duplicate chunks from the wrong file can crowd out the right owner.
3. AI-generated concept-map indexing is not yet part of the main index. This may help informal questions.
4. Local small LLMs are not guaranteed to be good rerankers. We need to compare them against Gemini rerank and specialized rerankers.
5. Gemini embeddings must be compared against local Qwen embeddings in the same pipeline and dataset, not inferred from separate runs.
6. `hit_rate@5` was missing and is now added; older reports need reruns to populate it.
7. Final benchmark runs must include full prompt traces. A run is audit-complete only when `llm_rerank_prompt.payload.prompt` is present in the trace, not just `prompt_chars`.

## Embedding Model Comparison So Far

These are the comparable full-100 Protogen runs we already have. Older rows do not have `hit_rate@5` because the metric was added after those runs.

| Embedding model | Reranker / strategy | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Qwen3 Embedding 0.6B 4-bit | Deterministic hybrid | 0.52 | 0.72 | pending rerun | 0.86 | 0.634 | Best practical local default so far. |
| Qwen3 Embedding 0.6B 4-bit | Gemini Flash Lite compact rerank | 0.73 | 0.86 | pending rerun | 0.90 | 0.792 | Strong quality/latency balance. |
| Qwen3 Embedding 0.6B 4-bit | Gemini Flash Lite file-first rerank | 0.76 | 0.90 | pending rerun | 0.94 | 0.832 | Best completed embedding+rerank profile so far. |
| Qwen3 Embedding 4B 4-bit | Deterministic hybrid | 0.56 | 0.76 | pending rerun | 0.90 | 0.673 | Most accurate raw local candidate generator so far. |
| Qwen3 Embedding 4B 4-bit | Gemini Flash Lite compact rerank | 0.69 | 0.83 | pending rerun | 0.92 | 0.766 | Worse than 0.6B after rerank. |
| Qwen3 Embedding 4B 4-bit | Gemini Flash Lite file-first rerank | 0.76 | 0.88 | pending rerun | 0.92 | 0.820 | Ties Hit@1, loses Hit@3/Hit@10/MRR to 0.6B. |
| Gemini Embedding 001, 1536 dims | Not completed | pending | pending | pending | pending | pending | Vertex suite exists; blocked by ADC refresh until reauth works. |
| Gemini Embedding 001, 3072 dims | Deterministic hybrid | 0.61 | 0.82 | 0.88 | 0.92 | pending table refresh | Best raw embedding baseline measured so far; Gemini API run indexed 12,698 items in 431s. |

Current answer:

| Question | Current answer |
| --- | --- |
| Best completed practical local embedding | Qwen3 Embedding 0.6B 4-bit. |
| Best completed raw local candidate generator | Qwen3 Embedding 4B 4-bit. |
| Best completed raw candidate generator overall | Gemini Embedding 001 at 3072 dims. |
| Best completed overall search profile | Qwen3 Embedding 0.6B 4-bit + Gemini Flash Lite file-first rerank. |
| Did we prove Gemini embeddings are worse or better? | Raw deterministic retrieval: Gemini 001 3072 is better than the completed Qwen local baselines. Reranked matrix is still incomplete. |
| Did we prove the best local LLM reranker? | Not fully. Most local LLM runs are 30-case experiments; full-100 matrix is incomplete. |

## What The Next Matrix Must Cover

The missing fair comparison is:

| Embedding | Candidate generation | Rerankers |
| --- | --- | --- |
| Qwen3 Embedding 0.6B 4-bit | Same hybrid/graph/symbol index | Gemini Flash Lite, Qwen 3.5 4B variants, Gemma E2B/E4B variants |
| Qwen3 Embedding 4B 4-bit | Same hybrid/graph/symbol index | Gemini Flash Lite, best local rankers |
| Gemini Embedding 001 1536 dims | Same hybrid/graph/symbol index | Gemini Flash Lite, best local rankers |
| Gemini Embedding 001 3072 dims | Same hybrid/graph/symbol index | Gemini Flash Lite, best local rankers |

Only after this matrix can we say "optimal" and "most accurate" with confidence.

## Working Hypothesis

The most promising production shape is hybrid:

1. Deterministic comprehensive index: file summaries + chunks + symbols + structural chunks + graph.
2. Optional AI memory notes during indexing, stored as evidence-linked searchable items.
3. Query-time candidate generation from multiple cheap signals.
4. Short-list rerank by the best available LLM or specialized reranker.
5. Targeted verification reads over top 3-5 only.

This uses embeddings for recall, lexical/symbol/graph signals for precision, and LLM reasoning only where it has leverage: query planning, reranking, and final verification.
