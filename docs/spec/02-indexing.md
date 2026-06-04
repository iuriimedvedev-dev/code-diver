# 02 — Indexing

Build a searchable index from a repository: **scan → extract items → embed → store**
(+ optional graph build).

Entry: `cli.py` `cmd_index` / hidden `cmd_index_selected` →
`services/indexing_service.py`.

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
- Emits configured item kinds: line chunks, structural chunks, symbols, file summaries,
  and file manifests.
- The built-in H5 default disables durable line/symbol body chunks and emits compact
  `file_summary` + `file_manifest` items.
- Fixed-window chunking remains available for research configs through
  `scanner.line_chunks: true` and `scanner.chunk_lines`.

**Contract**: deterministic — same repo + config => identical items.
⚠️ Divergence (I-7): chunk **stride == chunk size, no overlap**. A symbol spanning a
chunk boundary is split (signature in chunk N, body in chunk N+1), degrading retrieval
for boundary-spanning definitions. The spec for high-quality chunking calls for a
sliding window with overlap. **Structural chunking** (below) is the partial attempt at
boundary-aware chunking. In H5, durable source chunks are not the production default;
the chunking caveat applies to explicit deep-index/research profiles.

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

**Current default profile:** file-first indexing. The durable index emits compact
`file_summary` and `file_manifest` items and keeps source-code chunks/symbol bodies out
of the persistent vector store. Search returns ranked files first; detailed code evidence
is gathered later through read-only tools or a localized temporary index.

**Eval result:** structural chunking **hurt Hit@1** (0.64 → 0.53 with
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

## Streaming / replace indexing — `services/indexing_service.py`

`IndexingService._embed_and_save` detects a vector store exposing `replace_batches()`
and embeds/saves in **blocks** (`block_size = batch_size * workers * 8`) to bound memory
for large repos. Qdrant implements `replace_batches()` through a staging collection:
embed/upsert all batches into staging, publish the staging collection as the live alias
only after success, then delete the old target collection.

This fixes the former I-1W failure mode where a mid-stream failure could leave the live
Qdrant collection half-written. Transient embedding/provider failures can still abort the
indexing run, but the previous live alias remains intact when Qdrant staging has not been
published.

## Deterministic-indexing toggles (commit `eb63c2a`)

`ScannerConfig` toggles enforce the H5 default policy "**compact deterministic indexing,
LLM after retrieval**" (`docs/deterministic-indexing.md`):

- `line_chunks` (library default `True`, H5 default `False`) — emit fixed-line chunks.
- `file_summary_chunks` (H5 default `True`) — emit one compact summary item per file.
- `file_manifest_chunks` (H5 default `True`) — emit one path/import/symbol manifest item
  per file.
- `max_symbols_per_file` (H5 default `96`) — cap symbols used in file metadata.

⚠️ Divergence (D-1): `line_chunks=false` **silently disables `structural_chunks`** too —
the two flags are coupled, so turning off line chunks unexpectedly removes structural
chunks even when `structural_chunks=True`.

## Embedding — `services/parallel_embedding_service.py`

| `workers` | Behaviour |
|-----------|-----------|
| `1` (default) | Sequentially sends configured `batch_size` batches |
| `>1` | Splits into `batch_size` (default 32) batches, runs in a thread pool |

**Contract**: respect provider per-call limits regardless of worker count; retry
transient failures (`EMBEDDING_RETRY_ATTEMPTS = 3` exists in defaults).
⚠️ Divergences:
- (I-1) A provider error still aborts the indexing run. With Qdrant staging this should
  not corrupt the previous live collection, but local/API embedding retries remain an
  important reliability gap.
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
