# Explanation

This document is the plain-language map of what Code Diver is doing, why we test several search strategies, and where the current weak spots are.

## Big Picture

We have two separate phases:

1. **Index once.** Traverse a repository, build searchable representations, store them in Qdrant plus local artifacts.
2. **Search many times.** For each user query, generate candidates cheaply, then optionally ask an LLM to rerank or verify a short list.

The key rule: indexing quality defines the ceiling. If the right file is not present in the candidate set, no reranker can recover it.

## Current Direction: H5 By Default, Small Hot Locator Underneath

For a large repository like IntelliJ, indexing every chunk of source code is the wrong default. It creates a second copy of the repository inside the vector DB, increases RAM/storage, and gives the reranker too many near-duplicate candidates.

The current default shape is H5:

```text
local Qwen file-metadata embeddings
-> H3 deterministic hybrid file candidates
-> Gemini 3.1 Flash Lite top-10 LLM rerank
-> targeted read/grep/symbol inspection for the final answer
```

H3 is still the engine underneath H5. It builds the candidate set quickly and cheaply.
H5 adds one bounded LLM ranking step because our best measurements show that ranking,
not more permanent indexing depth, is the main user-visible quality lever.

The better physical index shape is still a two-layer system:

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

The first local embedding control used `qwen3-embedding:0.6b` with 1024 dimensions on the same file-locator index. It reached Hit@1 `0.628` and Hit@10 `0.890`. That is weaker than Gemini at rank 1, but close at top 10. In plain terms: the small local embedder often finds the right file, but ranks it too low. This makes it useful as a cheap candidate generator, while reranking still needs a stronger model or better search strategy.

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

For the benchmark, both branches must receive the same fixed top-30 files from the best locator. That isolates the question we actually care about: after the locator found a plausible neighborhood, is it better to inspect those files with tools or to build a deeper temporary vector index?

The grep/read branch should not be "LLM writes arbitrary grep and hopes." Real signatures are multiline, overloaded, generic, annotated, or formatted differently from the model's guessed pattern. The branch should expose structured tools:

| Tool | What it returns | Why it exists |
| --- | --- | --- |
| `file_outline` | Imports, classes, methods/functions, line ranges. | Lets the model inspect a file's table of contents before reading bodies. |
| `symbol_definition` | Fuzzy symbol matches inside candidate files. | Handles `updateUser`, `update_user`, overloads, annotations, and multiline signatures better than raw grep. |
| `bounded_rg` | Literal/regex hits inside only the top-30 files. | Still best for exact strings, logs, config keys, annotations, and constants. |
| `read_range` | A bounded line range. | Verifies evidence after the model has a specific target. |

The ephemeral index branch should build syntax-aware chunks from those same top-30 files. Every embedded chunk needs an ownership breadcrumb:

```text
[file: src/foo/UserController.kt] -> [class: UserController] -> [function: updateUser]
<body or structural chunk>
```

That breadcrumb is not decoration. It helps the embedding model and the LLM keep behavior attached to the owning file/class instead of ranking a detached function body.

Measure this branch with separate timers:

| Timer | Meaning |
| --- | --- |
| `ephemeral_build_ms` | Parse files, create chunks, embed chunks, and write/query-ready temporary vectors. |
| `ephemeral_query_ms` | Search an already-built temporary index. |
| `rerank_ms` | LLM/cross-encoder ranking after candidates are returned. |

For quality experiments, compare Hit/MRR/precision/recall with the embedding runtime already warm. Then optimize cache reuse and IDE incremental updates separately.

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

## Current Post-Ranking Hypotheses

The IntelliJ 1000-case benchmark now compares four post-locator branches over the same compact local Qwen file-locator index:

| Branch | Flow | Purpose |
| --- | --- | --- |
| A | locator -> outline/symbol/rg probes -> LLM rerank | Baseline structured inspection after the file locator. |
| B | locator -> ephemeral syntax-aware index over candidate files -> LLM rerank | Tests whether localized deep vectorization beats direct probes. |
| C | multiple locator profiles -> outline/symbol/rg probes -> LLM rerank | Tests whether fusing lexical-heavy, path/symbol, balanced, and vector-wide retrieval improves candidate recall. |
| D | LLM query planner + deterministic symbol hypotheses -> multi-query profile union -> probes -> LLM rerank | Tests whether the LLM should help before retrieval by generating better search intents and likely symbol names. |

The important discovery is that Branch A and B were not primarily ranker problems. Branch A called `outline`, `symbols`, and `rg`, but then appended their candidates after the locator list and truncated back to the candidate limit. Branch B often put ephemeral chunks before locator files and could push good locator candidates out. The runner now uses source-balanced candidate mixing so tools get real slots instead of being called for nothing.

Branch D exists because a real failure showed the limit of a single semantic query. The query `where is project opening orchestrated` did not retrieve `ProjectManagerImpl.kt` in the top locator candidates. But a symbol-like variant such as `ProjectManagerImpl` did retrieve it, and Gemini reranked it to rank 1 once it was present. So the LLM's highest-value job is not only final ranking; it is also generating alternate code-navigation queries before retrieval.

Diagnostics now record per case:

| Field | Meaning |
| --- | --- |
| `locator_rank` | Rank of the expected file in the first plain locator call. |
| `candidate_rank` | Rank after branch-specific candidate construction. |
| `rerank_rank` | Final rank after LLM rerank. |
| `query_variants` | Branch D planner/heuristic query variants. |
| `expected_sources` | Which tools or retrieval profiles found the expected file. |

This separates three different problems: the locator never saw the file, candidate construction dropped it, or the ranker demoted it.

### Requested 6-Way Post-Locator Matrix

The explicit matrix we tested was:

- 2 post-locator approaches:
  - **Branch A:** file candidates -> structured `outline`/`symbols`/`rg` probes -> LLM rerank.
  - **Branch B:** file candidates -> temporary syntax-aware vector index over those files -> vector search -> LLM rerank.
- 3 rankers/orchestrator-rerankers:
  - Gemini 3.1 Flash-Lite via Vertex.
  - Gemini 3.5 Flash via Vertex.
  - Qwen3.5 4B OptiQ 4bit via local MLX-compatible server.

Results on the original narrow IntelliJ 1000-case expected set.

Important: these numbers are not the final product-quality numbers after the answer-set correction. They are still useful for comparing Branch A vs Branch B under the same old evaluator, but they undercount broad multi-file answers. The 6-way matrix must be rerun on `datasets/intellij_eval_1000.answer_sets.jsonl` before we use it for final model selection.

| Ranker | Branch | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | Mean ms | Estimated cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.1 Flash-Lite | A grep/read/tools | 1000 | 0.700 | 0.815 | 0.828 | 0.850 | 0.850 | 0.085 | 0.760 | 2319 | $2.16 |
| Gemini 3.1 Flash-Lite | B ephemeral index | 1000 | 0.530 | 0.595 | 0.608 | 0.630 | 0.630 | 0.202 | 0.563 | 7301 | $2.28 |
| Gemini 3.5 Flash | A grep/read/tools | 1000 | 0.735 | 0.827 | 0.840 | 0.856 | 0.856 | 0.086 | 0.785 | 3070 | $13.51 |
| Gemini 3.5 Flash | B ephemeral index | 1000 | 0.562 | 0.601 | 0.621 | 0.635 | 0.635 | 0.218 | 0.585 | 8436 | $14.03 |
| Qwen3.5 4B OptiQ 4bit | A grep/read/tools | 1000 | 0.598 | 0.762 | 0.802 | 0.825 | 0.825 | 0.083 | 0.688 | 11517 | $12.39 estimator |
| Qwen3.5 4B OptiQ 4bit | B ephemeral index | 50 partial | 0.420 | 0.580 | 0.600 | 0.640 | 0.640 | 0.186 | 0.503 | 11462 | $0.66 estimator |

Interpretation:

- **Branch A clearly wins.** It is both more accurate and faster for all full runs.
- **Branch B did not justify itself.** Localized temporary vectorization over candidate files added build/query cost and reduced Hit@10 by roughly 22 points for both Gemini rankers.
- **Gemini 3.5 Flash was the best strict ranker** on the narrow expected set, but the gain over Flash-Lite was small for Hit@10: `0.856` vs `0.850`.
- **Flash-Lite is the best cost/latency tradeoff** in this matrix: near Gemini 3.5 Hit@10 at much lower cost.
- **Qwen3.5 4B local was usable but weaker** as a generative reranker. It was slower in this setup and lower on Hit@1/Hit@10.
- The ephemeral branch's higher `Precision@10` is misleading: it returns fewer repeated file-level hits but misses the expected file much more often.

The later answer-set evaluation changed the dataset, not the branch winner. However, it means the old 6-way absolute metrics are conservative and not directly comparable to the final `Hit@10=0.976` answer-set gate. The best production direction remains:

```text
compact persistent file/manifest locator
-> hybrid profile union
-> structured probes when useful
-> Gemini rerank
-> answer-set-aware evaluation
```

### Agentic H3 Status

The latest 100-case IntelliJ run compared a direct deterministic H3 branch against an agentic loop where Gemini 3.1 Flash Lite starts the search, calls tools, and then reranks/verifies candidates.

Gemini 3.5 Flash is not part of the active matrix now because the cost is too high for repeated experiment loops.

| Strategy | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | nDCG@10 | MAP@10 | Mean ms | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pure H3 + Gemini 3.1 Flash Lite rerank | 100 | 0.76 | 0.97 | 0.97 | 1.00 | 0.939 | 0.159 | 0.847 | 0.796 | 12,719 | $0.220 |
| Agentic H3 + Gemini 3.1 Flash Lite | 100 | 0.56 | 0.75 | 0.78 | 0.80 | 0.748 | 0.209 | 0.654 | 0.611 | 14,630 | $0.866 |
| Agentic H3 bounded tools + Gemini 3.1 Flash Lite | 100 | 0.55 | 0.73 | 0.74 | 0.75 | 0.679 | 0.282 | 0.607 | 0.562 | 15,055 | $0.870 |
| Agentic H3 bounded tools + Qwen3.5 4B local | 100 | 0.65 | 0.79 | 0.81 | 0.85 | 0.777 | 0.145 | 0.701 | 0.654 | 44,570 | local |

Current conclusion:

```text
Agentic fast-H3 currently loses to Pure full-H3.
```

This is not a rejection of agentic search in general. It means the present loop is too open-ended: it makes more model calls, sometimes runs broad grep/rg probes, and still gets weaker candidates than the tuned deterministic H3 branch. The next useful test is not "more agent"; it is a controlled split:

1. deterministic fast-H3 plus one rerank, to isolate the fast candidate generator;
2. agentic query planning over the same deterministic H3 candidate construction;
3. agent only on low-confidence/hard cases after Pure H3 has already run;
4. stricter tool policy: grep/rg should be scoped to candidate files once candidates exist.

### Agentic Tooling Problems We Hit

The agentic idea is still right at the product level: the LLM should choose search words, run tools, verify evidence, and rank the answer. The failure mode is that a large repository makes every vague or broad tool call expensive. The agent needs tools that are powerful but bounded by construction.

| Problem | What happened | Why it hurt | Fix |
| --- | --- | --- | --- |
| Broad text probes | The model called `code_diver_rg`/`code_diver_grep` without `path` after H3 had already found candidate files. | IntelliJ-wide regex/literal scans added seconds and often returned weak unrelated matches. | Unscoped grep/rg now automatically search only the current candidate bank once candidates exist. |
| Parallel batch race | The model put `code_diver_h3_search` and unscoped `code_diver_rg` in the same `tool_calls` array. | The runtime executed them in parallel, so rg started before candidate bank existed and still scanned the whole repo. | Orchestrator now stages first-pass candidate tools before delayed probes when a batch mixes candidate generation with unscoped probes. Result order is preserved. |
| Full-repo symbol scans | `code_diver_symbols` was treated as safe when H3 was available. The model could call it without path, or with a path like `java`. | A path such as `java` scanned tens of thousands of files; one trace showed 47,194 scanned files and a 17.5s symbol call. | Symbols now require a path or candidate bank when H3/search exists. After candidates exist, unscoped symbols and broad symbol directories are intersected with candidate files. |
| Prompt-only control | Earlier constraints existed mostly as instructions. | LLMs sometimes ignore or creatively reinterpret instructions under pressure. | Expensive behavior is now enforced in executor/orchestrator code, and the prompt/manifest describe the enforced contract. |
| Too many verification rounds | The agent keeps reading/probing after enough candidates exist. | It spends tokens and latency without improving candidate recall. | Rerank is forced after candidate-producing passes, but we still need a confidence-gated stop policy. |

The important lesson: for large repos, tool descriptions are not enough. The runtime must protect the search budget. The LLM should decide *what* to search, but the tool layer must decide *how far* a probe is allowed to expand.

The bounded-tool direction we are testing now is:

```text
LLM chooses query variants
-> H3/file locator returns candidate files
-> grep/rg/symbols/outline are automatically scoped to those candidates
-> reranker ranks the candidate bank
-> read only final evidence ranges
```

This preserves the useful part of the agentic approach while preventing accidental repository-wide scans.

The bounded run fixed tool latency but did not fix quality. On 100 IntelliJ cases, bounded Agentic H3 dropped to Hit@10 `0.75` while Pure H3 stayed at Hit@10 `1.00`. The useful conclusion is that broad scans were a real bug, but not the main quality limiter.

After bounding, tool timings looked healthy:

| Tool | Mean ms | P95 ms | Meaning |
| --- | ---: | ---: | --- |
| `code_diver_symbols` | 13.6 | 21.5 | Symbol probes are now candidate-scoped instead of scanning huge directories. |
| `code_diver_rg` | 191.9 | 390.4 | Regex probes are now bounded to candidate files. |
| `code_diver_grep` | 287.4 | 368.4 | Literal probes are now bounded to candidate files. |
| `code_diver_rerank` | 2,507.8 | 4,606.6 | Reranking/model calls are now the dominant latency. |

So the next quality lever is not more raw tool freedom. It is better policy:

1. run Pure H3 first;
2. look at confidence, score margin, source agreement, and whether expected answer type is multi-file;
3. invoke the agent only for low-confidence/hard cases;
4. make the agent use H3 as a query-planning/reranking assistant, not as an open-ended replacement for deterministic retrieval.

Qwen3.5 4B local is a useful counterpoint: it beat bounded Gemini Lite on the 100-case slice, but at roughly 3x the Gemini bounded latency and 3.5x the Pure H3 latency. That suggests the local model may be useful for offline sweeps or hard-case reranking, but not as the default interactive orchestrator unless we reduce model turns sharply.

## Final 2026-06-04 Research Slice

The current research slice is closed for architecture direction. The saved metrics say:

```text
H5 is the product default.
Pure H3 is the fast deterministic candidate generator and no-API fallback.
Agentic H3 is currently worse, more expensive, and slower.
Gemini 3.5 Flash is the quality ceiling but not a routine model because of cost.
Gemini 3.1 Flash Lite is the default quality/cost reranker.
Qwen3.5 4B local is viable as a local candidate, but too slow in the current agentic loop.
```

The strongest valid full result is the non-agentic H3 manifest answer-set run:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | Cost | Degraded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H3 manifest + Gemini 3.5 Flash | 1000 | 0.871 | 0.903 | 0.943 | 0.976 | 0.964 | 0.419 | 0.898 | 0.908 | 6542 | $34.94 | 0 |

This proves the `Hit@10 >= 0.95` target is reachable, but it is too expensive for routine iteration.

The public reviewer-runnable default is now the CodeSearchNet/MTEB Python 1000-case
local positive slice with Qwen-backed H5:

| Setup | Cases | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Mean ms | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pure H3 quality | 1000 | 0.823 | 0.919 | 0.944 | 0.961 | 0.961 | 0.177 | 0.875 | 0.900 | 555 | fast/no-API fallback |
| H5 quality | 1000 | 0.904 | 0.965 | 0.977 | 0.982 | 0.982 | 0.182 | 0.933 | 0.948 | 3020 | default quality path |
| H5 local | 1000 | 0.842 | 0.936 | 0.953 | 0.967 | 0.967 | 0.176 | 0.890 | 0.913 | 7708 | no-API ranker fallback |

These public-slice numbers are not official full-corpus MTEB scores. They are useful for
checking the Code Diver architecture with a downloadable benchmark and consistent
settings.

The current agentic evidence does not beat Pure H3:

| Setup | Cases | Hit@1 | Hit@10 | nDCG@10 | Mean ms | Cost | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pure H3 + Gemini Lite | 100 | 0.76 | 1.00 | 0.847 | 12,719 | $0.220 | valid calibration |
| Agentic H3 + Gemini Lite | 100 | 0.56 | 0.80 | 0.654 | 14,630 | $0.866 | valid calibration |
| Agentic H3 bounded + Gemini Lite | 100 | 0.55 | 0.75 | 0.607 | 15,055 | $0.870 | valid calibration |
| Agentic H3 bounded + Qwen3.5 4B local | 100 | 0.65 | 0.85 | 0.701 | 44,570 | local | valid calibration |

The attempted 1000-case agentic slice is not valid for search-quality selection:

| Run | State | Why not valid |
| --- | --- | --- |
| Pure H3 + Gemini Lite 1000 partial | 800 / 1000, `degraded=true`, `degraded_cases=372`, `rerank_errors=744` | Directional only; fail-soft fallback mixed into metrics. |
| Agentic H3 bounded + Gemini Lite 1000 | `error_count=555` | ADC reauthentication failures were counted as search misses. |
| Agentic H3 bounded + Qwen3.5 4B 1000 | zero-byte artifact | No usable metrics. |

Operationally, the next fix is not another model sweep. The runner must fail fast on ADC/auth failures, expose `valid/degraded/invalid` status in reports, and reject quality comparisons when degraded cases or rerank errors exceed a configured threshold.

The CLI now reflects this default: `evaluate --benchmark codesearchnet-mteb-python-1000`
uses `configs/codesearchnet-mteb-python-h5-qwen-quality.yml`. The old hash benchmark is
available only as `codesearchnet-mteb-python-hash-smoke` for no-key plumbing checks.
Human eval output prints selected settings, a progress bar over known case count, and a
metrics table. Use `--json` only when a script needs machine-readable output.

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

## Failure Modes To Test Explicitly

### Keyword Collapse

Developers often search with very short queries: method names, log fragments, config keys, or two-word phrases like `auth token`. Dense embeddings can over-interpret these queries and miss the obvious exact match.

Mitigation: strict hybrid search. Keep dense vectors for intent, but route exact/path/symbol-looking queries toward sparse signals: BM25, literal grep, regex, path, and symbol names. Our IntelliJ file-locator sweep already shows this: the lexical-heavy profile improved Hit@1 from `0.729` to `0.744` on the same index.

### Reranking Pitfall

A generic text reranker can hurt code search. If a reranker was trained mostly on prose relevance, it may demote syntactically exact code hits because it does not understand file ownership, APIs, wrappers, generated code, or implementation-vs-test intent.

Mitigation: rerank only after measuring rank deltas, and prefer code-oriented rerankers or prompts that preserve strong exact evidence. Treat rerank as conditional:

- use no rerank when rank 1 has a strong exact/path/symbol margin;
- use Gemini/Vertex rerank for ambiguous semantic queries;
- use llama.cpp `/v1/rerank` only with dedicated code/rerank models and small candidate limits;
- always log before/after gold rank.

### Blind Chunking

Fixed-size chunks cut functions, classes, imports, and call context apart. That creates embeddings that are neither complete code units nor good file locators.

Mitigation: use syntax-aware chunks for deep indexes. The persistent index can stay file-level, but the H2 temporary deep index over candidate files should chunk by functions/classes/methods where possible and attach path, parent class, imports, and nearby symbol metadata to every chunk.

## Current Main Strategies

| Strategy | What happens | What it tests |
| --- | --- | --- |
| `hybrid_candidates_symbol_first` | Deterministic vector + lexical + path/symbol fusion. No LLM rerank. | Cheap candidate quality and raw embedding quality. |
| `hybrid_rerank` / H5 | H3 hybrid candidates, then one bounded LLM top-10 rerank. | Current default quality path. |
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
2. Let the Search agent form the code-navigation intent and decide whether simple search is enough.
3. Run H5 retrieval by default: H3 vector/lexical/path/symbol candidates, then bounded LLM rerank.
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
