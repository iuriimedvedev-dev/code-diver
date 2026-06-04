# Indexing & Search Quality — Improvement Proposals

**Date:** 2026-06-01 · **Baseline:** `protogen_eval_100` (100 cases). Grounded in current
metrics + 2024–2026 code-RAG SOTA. Framed as hypotheses for the existing experiment runner.

## Where we stand (the diagnosis)

| Strategy | NDCG@10 | MRR@10 | hit@1 | hit@10 | latency |
|----------|---------|--------|-------|--------|---------|
| `vector_qdrant` | 0.679 | 0.720 | 0.640 | 0.880 | 31 ms |
| `hybrid_no_llm` (deterministic) | 0.683 | 0.721 | 0.630 | 0.890 | 134 ms |
| `hybrid_modern_graphrag` | 0.682 | 0.718 | 0.620 | 0.900 | 139 ms |
| `hybrid_llm_rerank` (file_first) | **0.735** | **0.785** | **0.700** | **0.930** | 4 580 ms |

Three facts drive every proposal below:

1. **Deterministic hybrid barely beats plain vector** (+0.004 NDCG) for 4× latency, and
   actually *lowers* hit@1 (0.630 vs 0.640). Adding more signals on top of a generic
   embedding is not the lever — **signal quality and ranking are.**
2. **The only large gain comes from a 4.58 s/query LLM rerank** (+0.05 NDCG, +0.07 hit@1).
   We jump straight from cheap-deterministic to a 35× slower call with **no cheap
   cross-encoder stage in between.**
3. **hit@1 is the weak spot everywhere** (0.62–0.70). Semantic queries: vector alone wins;
   hybrid fusion demotes correct results. Workflow is the weakest bucket.

Compounding context: the embedding model is **generic** (`gemini-embedding-2` 768d, or
`mxbai-embed-large` in the Ollama eval config) — *not* code-specialized; encoding is
**symmetric** (no `CODE_RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT` task prefixes); chunking
is **fixed 120-line, no overlap**; and **route-conditional weighting is implemented but
disabled** (`routing_enabled=False`).

---

## Prerequisite (do this first or you can't trust anything)

### P-0 · Trustworthy eval set
**Problem:** 100 cases; some query→target pairs risk being verbatim-derived from code
(Voyage's critique: inflates scores, low discrimination). hit@1 movements of ±0.02 are
within noise at n=100.
**Action:**
- Expand to ~250–400 cases; **paraphrase intent**, don't copy identifiers from the target.
- **Hard-negative mining**: for each query, add near-miss files (same module, similar name)
  as explicit negatives so the set distinguishes near-hits from true hits.
- Keep per-bucket counts balanced (semantic/path/symbol/workflow/exact) and report
  per-bucket NDCG@10 + hit@1 with confidence intervals.
- Add a **downstream signal** later (CodeRAG-Bench style Pass@k) to confirm retrieval gains
  actually help generation.
**Effort:** M · **Why first:** every experiment below is measured against this set.

---

## Tier 0 — Free / near-free wins (1–2 days each, validate immediately)

### T0-1 · Asymmetric embedding task prefixes
**Lever:** Gemini/Vertex expose `task_type` (`CODE_RETRIEVAL_QUERY` for the query,
`RETRIEVAL_DOCUMENT` for items). We currently embed both sides symmetrically
(`code_item.to_embedding_text` + same path for queries). Omitting the query instruction
costs a reported **1–5%** and we're leaving the model in the wrong mode.
**Change:** thread a query/document role through `EmbeddingProvider.embed_query` vs
`embed_documents`; set the task type per provider.
**Effort:** S · **Expected:** +1–5% NDCG, mostly on semantic. **Risk:** none.

### T0-2 · Turn on route-conditional fusion (it's already built)
**Lever:** `HybridQueryRouter` exists but `routing_enabled=False`. Per-bucket data already
shows routing wins where generic hybrid loses: path_symbol → lexical/path-heavy,
workflow → graph-assisted, semantic → near-pure vector.
**Change:** enable routing; make RRF/weights conditional on route (BM25-heavy for
identifier/exact queries, vector-pure for semantic, graph-on for workflow).
**Effort:** S · **Expected:** recover the hit@1 that flat hybrid loses on semantic, lift
path_symbol/workflow. **Risk:** low — gated, reversible per config.

### T0-3 · Fix the "hybrid demotes good vector hits" failure
**Lever:** flat hybrid lowers hit@1 vs vector → fusion is over-mixing on semantic queries.
**Change:** add a **score-margin guard** (already half-present: `preserve_top_candidate`,
`preserve_top_score_margin`) — when the top vector hit is confidently ahead, don't let
weak lexical/graph signals demote it. Tune on semantic bucket.
**Effort:** S · **Expected:** hit@1 recovery on semantic. **Risk:** low.

---

## Tier 1 — Biggest single levers

### T1-1 · Code-specialized embedding model ★ highest impact
**Lever:** we run a **generic** embedder. SOTA code embedders report **+13–20%** on code
retrieval over generic models:
- API path: **voyage-code-3** (+13.8% vs text-embedding-3-large; Matryoshka + int8/binary
  to control index cost).
- Open / self-host path (fits our `openai_compatible`/Ollama provider): **CodeXEmbed /
  SFR-Embedding-Code** (#1 on CoIR, beats Voyage), **Qodo-Embed-1-1.5B** (CoIR 68.5),
  **jina-code-embeddings-1.5b**.
**Change:** add the model as an embedding provider variant (abstraction already supports
it); re-index; run head-to-head as a hypothesis. Pair with T0-1 task prefixes.
**Effort:** S–M (mostly re-index + eval) · **Expected:** the largest jump on the board,
across all buckets, *before* any rerank. **Risk:** dimension/cost change — use Matryoshka
truncation to keep Qdrant footprint sane.

### T1-2 · AST-based structural chunking (cAST)
**Lever:** fixed 120-line chunks split functions/classes across boundaries (audit I-7).
**cAST** (tree-sitter, recursively split large nodes + merge siblings to a size budget)
reports **+4.3 Recall@5 / +2.67 Pass@1** vs line chunking, and is language-agnostic.
**Change:** replace `_chunk_file` stride logic with syntactic-unit chunks; reuse/extend
the existing symbol extractor toward tree-sitter so non-Python gets real boundaries too.
**Effort:** M · **Expected:** recall + hit@1, especially symbol/workflow buckets.
**Risk:** medium (touches indexing core) — keep line-chunking as a config fallback for
A/B.

---

## Tier 2 — Ranking & context (close the gap to LLM rerank, cheaply)

### T2-1 · Cross-encoder reranker as a fast first stage ★ best latency/quality trade
**Lever:** today it's deterministic (0.68 NDCG) → **4.58 s** LLM rerank (0.735). A
cross-encoder gives **15–40% precision lift at sub-second latency**: **Voyage Rerank 2.5**
(~0.6 s, best balance) or **jina-reranker-v3** (<200 ms) hosted; **bge-reranker-v2-m3**
self-hosted.
**Change:** insert a reranker stage between hybrid candidates and the (optional) LLM
rerank. Likely captures most of the +0.05 NDCG for ~1/8th the latency; keep LLM rerank as
an optional top-tier mode for hard queries only.
**Effort:** M · **Expected:** approach 0.72–0.73 NDCG at <700 ms; big hit@1 gain.
**Risk:** new dependency — but composes cleanly as a strategy wrapper.

### T2-2 · Contextual Retrieval headers (Anthropic)
**Lever:** prepend a short LLM-generated "this chunk is from {file}/{class}, it does X"
header to each chunk before embedding **and** BM25 indexing. Reported **−35% retrieval
failures (contextual embeddings), −49% with contextual BM25, −67% with reranking.**
**Change:** add an index-time enrichment step using the enclosing file-summary/class as
context (we already build file summaries — cheap context source). Cache with prompt
caching to bound cost.
**Effort:** M · **Expected:** large failure-rate reduction, compounds with T1-1/T1-2.
**Risk:** index-time LLM cost — gate behind config; it's an offline one-time cost per index.

---

## Tier 3 — Query understanding (target the weak buckets)

### T3-1 · HyDE for the semantic/NL route
**Lever:** semantic queries are where vector wins but hit@1 is weak. Generate a
hypothetical implementation from the NL query, embed *that*. Reported large precision/recall
gains with no labels.
**Change:** add a HyDE pre-step gated to the semantic route (uses existing generation
provider). **Effort:** S–M · **Expected:** semantic hit@1. **Risk:** +1 LLM call latency —
gate by route.

### T3-2 · Query decomposition for workflow/multi-faceted queries
**Lever:** workflow is the weakest bucket. Decompose into sub-queries, retrieve each, fuse
through the existing RRF stage. Reported **+36.7% MRR@10** on multi-faceted queries.
**Change:** add decomposition gated to workflow route; fuse via current RRF.
**Effort:** M · **Expected:** workflow NDCG/MRR. **Risk:** latency — gate by route.

---

## Tier 4 — Structural & stretch

### T4-1 · Multi-language graph via tree-sitter
**Lever:** `calls`/`references` edges are Python-only today. Tree-sitter call/import/
reference edges across languages + **small-to-big** parent expansion (retrieve method →
return enclosing class/file). Turns the Python-only graph into a real repo dependency graph.
**Effort:** L · **Expected:** workflow/cross-file queries. **Risk:** medium; build offline.

### T4-2 (stretch) · Late chunking or ColBERT late-interaction
Late chunking (cheap, needs a long-context code embedder) or ColBERT multi-vector
(token-level identifier matching, higher storage). **Pilot only if T1–T2 plateau.**

---

## Recommended sequencing

```
P-0  trustworthy eval set ───────────────────────────────┐ (prerequisite)
T0-1 task prefixes  ┐                                     │
T0-2 routing on     ├─ free wins, validate in days        │ measured
T0-3 margin guard   ┘                                     │ against
T1-1 code embedder  ── biggest lever, re-index + A/B      │ P-0
T1-2 AST chunking   ── indexing core                      │
T2-1 cross-encoder  ── collapse the 4.58s rerank cost     │
T2-2 contextual hdrs── compounding index-time enrichment  │
T3-1/T3-2 HyDE/decomp ─ per-route, target weak buckets    │
T4 structural/stretch ─ if earlier tiers plateau ─────────┘
```

**Expected trajectory:** T0 (+routing/prefixes) closes the "hybrid ≤ vector" gap and
restores hit@1; **T1-1 is the headline jump**; T2-1 delivers most of the LLM-rerank
quality at ~1/8th latency; T2-2/T3 chip at the residual weak buckets. Each is a discrete
hypothesis in the experiment runner, so every claim above is falsifiable against P-0.

## Key external references
cAST (arxiv 2506.15655) · Anthropic Contextual Retrieval · voyage-code-3 / SFR-Embedding-
Code (CoIR) · Vertex embedding task types · HyDE · query decomposition (arxiv 2507.00355) ·
CodeRAG-Bench · CoRNStack hard negatives.
