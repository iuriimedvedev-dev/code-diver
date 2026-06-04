# 02 — Indexing

Build a searchable index from a repository: **scan → extract items → embed → store**
(+ optional graph build).

Entry: `cli.py` `cmd_index` / `cmd_index_selected` → `services/indexing_service.py`.

## Pipeline contract

```
root ──▶ Scanner ──▶ Iterable[CodeItem] ──▶ EmbeddingTextPreparer ──▶ ParallelEmbeddingService ──▶ VectorStore.save
                                                                              │
                                                              (optional) CodeGraphBuilder ──▶ CodeGraphStore
```

`IndexingService.build`:
1. Selects a scanner by `indexing.mode`.
2. Materializes items.
3. Prepares embedding text (token/char bounded).
4. Embeds (batched, parallel).
5. Persists vectors with `VectorStore.save(...)`.
6. Optionally builds and stores the graph.

## Scanner modes (`indexing.mode`)

| Mode | Scanner | Behaviour |
|------|---------|-----------|
| `scanner` | `services/codebase_scanner.py` | Deterministic glob include/exclude, gitignore-aware, fixed-line chunking + symbol + file-summary items |
| `ai` | `ai_indexing/ai_codebase_scanner.py` | LLM proposes high-value files/patterns to index |
| `orchestrated` | `orchestration/orchestrated_codebase_scanner.py` | LLM produces an include/exclude *plan*, then base scanner runs |

### Deterministic scanner — `codebase_scanner.py`

- Walks repo honoring `.gitignore` (`inspection/ignore_matcher.py`) + configured
  include/exclude globs.
- Emits three item kinds: chunks, symbols, file summaries.
- Chunking: fixed window of `scanner.chunk_lines` (default 120).

**Contract**: deterministic — same repo + config ⇒ identical items.
⚠️ Divergence (I-7): chunk **stride == chunk size, no overlap**. A symbol spanning a
chunk boundary is split (signature in chunk N, body in chunk N+1), degrading retrieval
for boundary-spanning definitions. The spec for high-quality chunking calls for a
sliding window with overlap. **Structural chunking** (below) is the partial attempt at
boundary-aware chunking, but it is additive and off by default — the token-count line
chunks remain the production behaviour.

### Structural chunking (additive, off by default)

A new item kind `CodeItemIndexKind.STRUCTURAL_CHUNK` carries whole top-level
class/function spans instead of fixed line windows.

- Service: `services/structural_code_chunker.py` (`StructuralCodeChunker`). Uses the
  Python **AST** to find top-level class/function spans; falls back to the
  symbol-extractor for other languages.
- Integrated in `CodebaseScanner._chunk_file()` behind `ScannerConfig.structural_chunks`
  (default `False`).
- **Additive**: structural chunks coexist with the line chunks; they do **not** replace
  them.

**Eval result (not a default):** structural chunking **hurt Hit@1** (0.64 → 0.53 with
unsplit vector search; 0.59 with split-vector retrieval) and raised latency and index
size (~9,230 → 12,698 items). It remains opt-in.

### JVM symbol extraction — `code_symbol_extractor.py`

`code_symbol_extractor.py` now extracts JVM symbols via regex: Java/Kotlin
classes/interfaces/enums/records/annotations (`_JVM_TYPE_RE`) and Java/Kotlin methods
(`_JAVA_METHOD_RE`, `_KOTLIN_FUNCTION_RE`), guarded by `_CONTROL_WORDS` to filter out
keywords. This broadens symbol coverage beyond Python for large JVM repos (IntelliJ
scale).

⚠️ New finding J-1 (AUDIT-2026-06-02): the method regex creates **false symbols** from
`return x(` / `throw new Y(` statements when `symbol_chunks=True` — control-flow call
sites are misread as method definitions.

### AI scanner — `ai_indexing/`

- `AiIndexContextCollector` gathers repo tree / symbols / key config.
- `AiIndexPromptBuilder` builds the discovery prompt.
- `generation_provider.generate_json(prompt)` returns candidate selections.
- `AiIndexResponseParser` parses JSON → `AiIndexCandidate`s.

**Contract**: LLM output is *untrusted* and must be validated before touching the FS.
✅ Fixed (I-4): `AiCodebaseScanner` now catches generation/parse errors, records
`last_error`, and falls back to the base scanner — matching `IndexPlanOrchestrator`'s
graceful degradation. (Was: no try/except around the LLM call / `json.loads`, so a
refusal or malformed response crashed the whole index.)

### Orchestrated scanner — `orchestration/`

- `IndexPlanOrchestrator` → LLM → include/exclude `IndexPlan`.
- `IndexPlanSanitizer` validates the plan, then `CodebaseScanner` runs with it.

**Contract**: *all* LLM-supplied patterns pass the sanitizer; the sanitizer rejects
hidden paths, traversal, and unbounded includes.
✅ Fixed (I-5, I-6): `IndexPlanSanitizer.safe_exclude_additions` now sanitizes `exclude`
patterns too — rejecting hidden patterns, broad globs (`*.py`, `**/*`) and over-limit
patterns. `OrchestratedCodebaseScanner` logs `index_plan_rejected_include` /
`index_plan_rejected_exclude` for dropped patterns. (Was: `exclude` patterns bypassed the
sanitizer entirely, so an injected response could suppress indexing of whole languages.)

## Selected indexing — `services/selected_indexing_service.py`

`index-selected` reads agent-chosen path/line ranges from stdin JSON
(`selected_index_payload_parser.py`), builds items, and **appends** to the store via
`getattr(store, "append", store.save)`.

⚠️ Divergence (I-3): the main `IndexingService` only ever calls `save` (full
overwrite) — there is **no incremental indexing** of changed/new/deleted files. The
`append` path exists but is used only by selected indexing.

## Streaming / append indexing — `services/indexing_service.py:62-133`

`IndexingService._embed_and_save` now detects a vector store exposing `append()` and
indexes in **blocks** (`block_size = batch_size × workers × 8`) to bound memory for
large repos (IntelliJ scale): `save()` for the first block, `append()` for the rest.
This partially addresses prior I-3 by streaming rather than materializing all vectors at
once.

⚠️ **CRITICAL finding I-1W (AUDIT-2026-06-02)**: a mid-stream failure leaves Qdrant
**partially written with no rollback** — a regression of the previously fail-safe
single-pass path (where a failed index left no partial state). Combined with I-1 (no
retry around `future.result()`), one transient error can leave the collection in a
corrupt, half-indexed state.

## Deterministic-indexing toggles (commit `eb63c2a`)

New `ScannerConfig` toggles enforce the policy "**no AI during indexing, only after
retrieval**" (`docs/deterministic-indexing.md`):

- `line_chunks` (default `True`) — emit fixed-line chunks.
- `max_symbols_per_file` (default `None`) — cap symbols emitted per file.

⚠️ Divergence (D-1): `line_chunks=false` **silently disables `structural_chunks`** too —
the two flags are coupled, so turning off line chunks unexpectedly removes structural
chunks even when `structural_chunks=True`.

## Embedding — `services/parallel_embedding_service.py`

| `workers` | Behaviour |
|-----------|-----------|
| `1` (default) | Single `embed_documents(all_texts)` call — **batching skipped** |
| `>1` | Splits into `batch_size` (default 32) batches, runs in a thread pool |

**Contract**: respect provider per-call limits regardless of worker count; retry
transient failures (`EMBEDDING_RETRY_ATTEMPTS = 3` exists in defaults).
⚠️ Divergences:
- (I-10) With the default `workers=1`, `batch_size` is **dead** — a provider with a
  per-call document cap fails on large repos at `workers=1` but works at `workers=2`.
- (I-1) `future.result()` re-raises immediately and `IndexingService.build` has no
  surrounding retry/partial-save — **one transient network error aborts the entire
  index** with no partial state. The retry constant is not honored here.
- (2.1) `VertexEmbeddingProvider` loops one text per API call, defeating batching
  outright (see [07](./07-providers-and-storage.md)).

## Embedding text preparation — `services/embedding_text_preparer.py`

Formats and optionally truncates item text to `max_input_chars`.
⚠️ Divergence (I-2): truncation is a raw **character** slice — can cut mid-token /
mid-line, producing semantically broken embedding input. Token-boundary truncation is
the intended behaviour. (Only active when `EMBEDDING_MAX_INPUT_CHARS` is configured.)

## Index-time invariants

1. Items are gitignore- and glob-filtered before embedding.
2. Embedding dimension must match the target store's collection (see Qdrant lifecycle
   in [07](./07-providers-and-storage.md); ⚠️ 2.4/2.5 blind spots).
3. Graph build is optional and must not block vector indexing.
