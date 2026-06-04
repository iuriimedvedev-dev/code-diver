# 07 — Providers & Storage

Pluggable, config-selected adapters for embeddings, generation, and vector persistence.

## Embedding providers — `providers/`

Contract: `embedding_provider.py`
```python
class EmbeddingProvider(ABC):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...
    dimensions: int
```
Factory: `provider_factory.py`, selected by `embedding.provider`
(`EmbeddingProviderId` StrEnum — properly typed).

| Provider | File | Notes |
|----------|------|-------|
| gemini | `gemini_embedding_provider.py` | Retry w/ exponential backoff; no fallback model |
| vertex | `vertex_embedding_provider.py` | Extends gemini for Vertex AI |
| openai | `openai_embedding_provider.py` | **No retry** |
| openai_compatible | `openai_compatible_embedding_provider.py` | Ollama/local; infers dimensions |
| hash | `hash_embedding_provider.py` | Deterministic 256-dim; reproducible local tests |

⚠️ Divergences:
- **(2.1) ✅ FIXED** `VertexEmbeddingProvider` now delegates to the batching parent
  (`embedding-2` contract) instead of one API call per document — a 400-chunk index is
  ~13 batched calls, not 400. Test:
  `test_vertex_embedding_provider_reuses_embedding_2_contract`.
- (2.3) Retry/fallback is **inconsistent**: gemini embed has retry but no fallback;
  openai embed has neither; gemini *generation* has fallback models but no in-model
  retry; openai generation has neither. The non-Gemini path is the least resilient.
- (2.4) `openai_compatible` passes `dimensions=0`; since `0` is falsy the field is
  omitted from the payload (intended for Ollama), and `IndexingService` **mutates**
  `provider.dimensions` after the first embed — dimension is unknown until then.
- (5.3) `gemini_embedding_provider._uses_embedding_2()` is a hardcoded
  `model == "gemini-embedding-2"` magic-string branch controlling API format — silent
  breakage on a future model name.

**Local model support (the big new direction, 2026-06-02):**
- **Local embeddings**: Qwen3-Embedding-0.6B / 4B-4bit-DWQ served through vLLM-Metal /
  MLX (OpenAI-compatible provider).
- **Local generative rerankers**: Gemma-4 E2B/E4B (4bit / bf16 / OptiQ) and Qwen3.5-4B
  via `mlx_lm.server`.
- New `OpenAIEmbeddingProvider.send_dimensions` flag (default `True`) — opt out of the
  `dimensions` param for models that don't support it.
- New `QueryCachingEmbeddingProvider` (`providers/query_caching_embedding_provider.py`)
  wraps any embedder with an in-memory **query-embedding cache**.
- `openai_compatible_generation_provider` now tolerates a missing `response_format` and
  parses content arrays / `reasoning_content` / `reasoning` / `text` fields.

⚠️ Divergences (AUDIT-2026-06-02):
- **(P-1)** `reasoning_content` can be returned **as the answer** — the parser may pick
  the model's thinking trace instead of the final content.
- **(P-3)** the loose rerank parser **mis-ranks** — tolerant field parsing accepts
  malformed orderings and produces wrong ranks.
- **(P-4)** `QueryCachingEmbeddingProvider` **snapshots `dimensions`** — a cached query
  embedding can carry a stale dimension if the provider's dimension is mutated later.

⚠️ The local rerankers are **generative models, not dedicated cross-encoders**, and the
serving stacks (Ollama / MLX) expose **no true cross-encoder rerank endpoint**. This is
flagged as the likely root cause of the local-vs-cloud quality gap (see the local-model
proposals in `.plans/`).

**Query/document prefixes (commit `5314a04`, "T0"):** embedding providers now support
`query_prefix` / `document_prefix` fields (OpenAI-compatible style) to differentiate
query vs document embedding text. ⚠️ This is **plumbing only** — no code-specialized
model swap and no reindex yet, so the empirical effect is **NEUTRAL**.

## Generation providers — `generation/`

Contract: `generation_provider.py` (Protocol)
```python
def generate_json(self, prompt: str) -> str: ...
def generate_json_result(self, prompt: str) -> GenerationResult: ...   # text + usage + latency + cost
```
Factory: `generation_provider_factory.py`, selected by `generation.provider`.

| Provider | File | Notes |
|----------|------|-------|
| gemini | `gemini_generation_provider.py` | Thinking budget, fallback models, structured JSON |
| vertex | `vertex_generation_provider.py` | Extends gemini for Vertex |
| openai | `openai_generation_provider.py` | No fallback, no retry |
| openai_compatible | `openai_compatible_generation_provider.py` | Generic OpenAI API |

⚠️ Divergences:
- (1.4) The factory matches `"openai"` / `"openai_compatible"` as **raw strings** while
  embedding/store have StrEnums. No `GenerationProviderId` enum — typos give a poor
  `ValueError`.
- (2.2) `generate_json_result` is on the Protocol, yet both orchestrators still
  `getattr(provider, "generate_json_result", None)` and fall back to `generate_json` +
  token *estimation*. Dead duck-typing that forks cost accounting (real vs estimated
  tokens).
- `GeminiGenerationProvider` has **no unit test**; its retry/fallback loop is untested
  (⚠️ 3.5).

**Pricing:** `ModelCostEstimator` gained new model price entries —
`gemini-3.1-flash-lite`, `gpt-5.1-mini`, Claude Opus 4.8, and Claude Haiku 4.5.

## Vector stores — `store/`

Contract: `vector_store.py`
```python
def save(self, ...): ...
def search(self, query_vector, limit) -> list[SearchResult]: ...
def append(self, ...): ...    # not in the ABC for all stores — duck-typed
def exists(self) -> bool: ...
def metadata(self) -> dict: ...
```
Factory: `vector_store_factory.py` (`VectorStoreProviderId` StrEnum).

| Store | File | Role |
|-------|------|------|
| json | `json_vector_store.py` | Flat-file, brute-force search; reproducible local runs |
| qdrant | `qdrant_vector_store.py` | HTTP client, local/cloud, collection-per-hypothesis isolation |

⚠️ Qdrant lifecycle divergences:
- **(2.5, Medium)** `append()` checks dimension by scrolling 1 existing point. If the
  collection exists but is **empty** (prior failed index), `metadata()` is `{}`,
  `existing_dimensions` is `None`, the check is **skipped**, and mixed-dimension vectors
  can be inserted — silent corruption.
- (3.3) `append()` has **no test** — neither happy path nor the dimension guard.
- Collection-per-hypothesis isolation prevents intra-run parallelism.

## Secrets

Keys read from environment via `settings/environment.py` (`GEMINI_API_KEY`,
`OPENAI_API_KEY`, `QDRANT_API_KEY` via `api_key_env` indirection, `GOOGLE_CLOUD_*`).
`.env` is gitignored.
⚠️ **(1.5, High)** ClickHouse has **no env-var entry** — `Defaults.CLICKHOUSE_PASSWORD =
"code_diver"` is hardcoded and committed in 7 YAML files. Every other credential has
indirection; this one does not.
⚠️ (2.6) No redaction layer — an HTTP error body containing a key could land in trace
JSONL.

## Provider/storage invariants (intended vs actual)

| # | Intended | Status |
|---|----------|--------|
| 1 | Provider swap is config-only | ✅ |
| 2 | Batching honored by all embed providers | ✅ FIXED — Vertex now batches (was 2.1) |
| 3 | Uniform retry/timeout policy | ❌ 2.3 |
| 4 | Stored vector dim always matches collection | ⚠️ 2.4 / 2.5 |
| 5 | All secrets via env indirection | ❌ 1.5 (ClickHouse) |
| 6 | Provider selection enum-validated | ⚠️ 1.4 (generation is raw strings) |
