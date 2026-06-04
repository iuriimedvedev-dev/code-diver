# Quality Improvement Proposals — v2 (post Flash-Lite / structural / split-vector)

**Date:** 2026-06-01 · Supersedes the prioritization in `2026-06-01_quality-improvement-proposals.md`.
Grounded in the latest `protogen_eval_100` results.

## What the new experiments told us

| Approach (new) | Hit@1 | Hit@10 | NDCG@10 | Latency | Cost/100 | Verdict |
|----------------|-------|--------|---------|---------|----------|---------|
| `vector_qdrant` (control) | 0.64 | 0.88 | 0.679 | 37 ms | $0 | baseline |
| hybrid routed + vector-guard (best deterministic) | 0.64 | 0.90 | 0.692 | 135 ms | $0 | NEUTRAL on Hit@1 |
| structural chunking (unsplit) | 0.53 | 0.87 | 0.627 | 196 ms | $0 | **HURT** |
| structural + split-vector | 0.59 | 0.91 | 0.672 | 561 ms | $0 | mitigated, still < baseline |
| T0 embedding prefixes | 0.64 | 0.90 | 0.692 | 135 ms | $0 | NEUTRAL (plumbing only, no reindex) |
| **Flash-Lite rerank (compact)** | **0.78** | 0.91 | 0.763 | 2.2 s | $0.135 | **WON (best value)** |
| **Flash-Lite rerank (file_first)** | **0.78** | **0.93** | **0.776** | 3.3 s | $0.325 | **WON (best quality)** |
| orchestrator rerank tool | 0.78 | 0.85 | 0.712 | 10.5 s | $0.415 | not production-ready |

### The three conclusions that should drive what we do next

1. **We have been optimizing the *ranking* stage, and it has nearly topped out.** Flash-Lite
   rerank is a real, cheap win (Hit@1 0.64→0.78). The orchestrator-tool variant adds cost
   and latency for *less* quality. There is little headroom left in "rerank harder."

2. **The ceiling is now in *retrieval/indexing*, not ranking.** The docs' own diagnostics:
   **6% of cases never appear in the top-40 candidate set** (reranking literally cannot fix
   them), deterministic **Hit@1 is plateaued at 0.64**, and **structural chunking *hurt***.
   You cannot rerank a document you never retrieved.

3. **The single biggest lever from v1 is still untouched.** The team built embedding
   prefix plumbing ("T0") but **never swapped in a code-specialized model and never
   reindexed** — it ran on generic `mxbai-embed-large`. Both my v1 analysis *and* the new
   `ranking-research-2026-06-01.md` independently estimate a code-aware embedder at
   **+0.05–0.10 Hit@1**. This is the highest-leverage move and it attacks the exact two
   weaknesses above (the 0.64 plateau and the 6% recall floor).

The strategic reframe: **stop adding ranking machinery; raise the floor of what retrieval
surfaces.**

---

## Proposals (a focused few, prioritized)

### Proposal 1 — Swap in a code-specialized embedding model + reindex ★ do this first
**Why now:** it is the only lever that moves the *retrieval floor* — the 6%-missing-from-top-40
cases and the deterministic 0.64 plateau. Reranking and fusion cannot reach these. The
prefix plumbing is already in place, so the integration cost is low; the work is mostly a
reindex + A/B.
**What:** add a code embedder as a provider variant and reindex `protogen_eval_100`:
- API path: **voyage-code-3** (reported +13.8% vs text-embedding-3-large; Matryoshka +
  int8/binary to bound Qdrant size).
- Self-host path (fits the existing `openai_compatible`/Ollama provider): **SFR-Embedding-
  Code / CodeXEmbed**, **Qodo-Embed-1-1.5B**, **jina-code-embeddings-1.5b**, or
  **granite-code** (the docs explicitly name granite-code as worth testing).
- Set the **correct asymmetric task types/prefixes** at the same time
  (`CODE_RETRIEVAL_QUERY` for queries vs `RETRIEVAL_DOCUMENT` for items) — the plumbing
  exists; make sure it's actually used, not left symmetric.
**Measure:** deterministic Hit@1/Hit@10/NDCG vs the generic-embedding baseline, *and* the
top-40 recall gap (does the 6% shrink?). Run **before** any reranker so the gain is
attributable to embeddings.
**Effort:** S–M (mostly reindex + eval) · **Expected:** +0.05–0.10 Hit@1 deterministic;
shrink the 6% floor — which then *also* lifts the Flash-Lite ceiling.
**Risk:** dimension/cost change — control with Matryoshka truncation.

### Proposal 2 — Symbol-first retrieval lane (exploit our strongest, ignored signal)
**Why now:** new diagnostic — **symbols are 53.4% of first-relevant hits**, yet hybrid does
no symbol-aware ranking and the split-vector profile gives symbols only 0.30 of the budget.
This is free signal we are under-weighting, and it is *deterministic* (no LLM cost) — the
right tool to lift the 0.64 plateau.
**What:** use the new `MultiIndexVectorRetrievalStrategy` machinery to (a) give symbols a
guaranteed first-class lane in the candidate set, and (b) add a **symbol-match prior** to
fusion — when query tokens match a symbol name/qualified name, boost that item's rank-1
candidacy. Tune `vector_kind_multipliers` with symbols weighted up for symbol/path buckets.
**Measure:** deterministic Hit@1 overall and on the symbol + path_symbol buckets;
`first_relevant_kind.symbol.rate` should convert to more rank-1 wins.
**Effort:** S · **Expected:** deterministic Hit@1 lift, especially symbol/exact buckets;
$0 inference. **Risk:** low — gated by config, reuses shipped machinery.

### Proposal 3 — Replace the LLM rerank with a local cross-encoder (cost & latency at scale)
**Why now:** Flash-Lite is great but costs **$0.135–0.325/100 and 2.2–3.3 s/query** — that
does not scale to a real codebase or CI. The docs themselves recommend "a fast local
cross-encoder or late-interaction (ColBERT) reranker." A cross-encoder gives most of the
ranking quality at **<300 ms and $0**.
**What:** add a cross-encoder rerank stage (self-host **bge-reranker-v2-m3**, or hosted
**jina-reranker-v3 / Voyage rerank 2.5**) as a strategy wrapper over the deterministic
candidates — same slot Flash-Lite occupies. Optionally **distill Flash-Lite's judgments**
into a local code reranker using hard-negative mining (see Proposal 5) for a code-tuned
model.
**Measure:** Hit@1/NDCG vs Flash-Lite file_first at a fraction of latency/cost. Keep
Flash-Lite as the optional top-tier mode for the hardest queries only (route-gated).
**Effort:** M · **Expected:** ~Flash-Lite quality at <300 ms, $0; makes the quality path
viable in production. **Risk:** new dependency; composes cleanly as a wrapper.

### Proposal 4 — Fix the workflow bucket (its Hit@1 is 0.56, the worst)
**Why now:** workflow is the weakest bucket by a wide margin, and graph expansion *helps
Hit@3/10 but hurts Hit@1* — a classic "good recall, bad rank-1" signature.
**What:** for the **workflow route only** (routing already exists): (a) **decompose** the
multi-step query into sub-queries, retrieve each, fuse via the existing RRF stage (reported
+36.7% MRR@10 on multi-faceted queries); (b) keep graph expansion for recall but apply the
new **`preserve_vector_top` / `vector_top_score_margin`** guard so a confident rank-1 isn't
demoted by graph neighbors.
**Measure:** workflow-bucket Hit@1/MRR/NDCG specifically.
**Effort:** M · **Expected:** workflow Hit@1 0.56 → mid-0.6s; minimal effect on other
buckets (route-gated). **Risk:** +1 LLM call on workflow queries only — bounded by routing.

### Proposal 5 — Enabler: hard-negative eval set + stage-level rank logging
**Why now:** at n=100, ±0.02 Hit@1 is noise, and today we only log final LLM-selection
indices — we can't see *why* a candidate moved between vector → lexical → graph → fused →
reranked. Proposals 1–4 are only trustworthy and diagnosable with this in place. The docs
request exactly this ("stage-level rank movement logging") and flag the noisy small set.
**What:** (a) expand to ~250–400 **intent-paraphrased** cases (not verbatim-from-code) with
**hard negatives** mined from near-miss files; (b) log per-candidate rank at each stage so
regressions like "structural hurt Hit@1" are explained, not just observed. This also closes
the still-open observability audit gap (4.1/4.2) and supplies the distillation data for
Proposal 3.
**Effort:** M · **Expected:** trustworthy, attributable gains; unblocks reranker
distillation. **Risk:** none — pure measurement/infra.

---

## Recommended sequencing

```
P5 eval set + stage logging ──┐ (enabler; do alongside P1)
P1 code-specialized embedder ─┴─ raises the retrieval FLOOR (the 6% + the 0.64 plateau)
P2 symbol-first lane ──────────── deterministic Hit@1, $0, reuses shipped split-vector
P3 local cross-encoder ────────── collapses Flash-Lite cost/latency at scale
P4 workflow decomposition+guard ─ targets the single worst bucket
```

**Do NOT** invest further in: the orchestrator rerank tool (10.5 s / $0.415 / lower Hit@10 —
shelve for research only) or structural chunking as a default (it hurt Hit@1; keep it
behind `structural_chunks=False` for recall-only workflows).

**Headline:** P1 + P2 are the two highest-leverage moves because they raise what retrieval
*surfaces* — the stage that is now the binding constraint — and they are cheap. P3 makes the
proven rerank win affordable; P4 fixes the worst bucket; P5 makes all of it trustworthy.

## External references
voyage-code-3 / SFR-Embedding-Code / Qodo-Embed / granite-code (CoIR) · Vertex embedding
task types · bge-reranker-v2-m3 / jina-reranker-v3 / Voyage rerank 2.5 · query decomposition
(arxiv 2507.00355) · CoRNStack hard-negative mining · Anthropic Contextual Retrieval (deferred).
```
