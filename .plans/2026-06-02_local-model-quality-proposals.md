# Improving Quality with Local Models — Proposals (2026-06-02)

**Context:** the team pivoted to a fully-local stack — Qwen3-Embedding-0.6B-4bit (vLLM-Metal)
+ generative LLM rerankers (Gemma-4 / Qwen3.5-instruct via `mlx_lm.server`). Grounded in the
2026-06-02 eval reports + external research. Supersedes the cloud-leaning v2 proposals for
the local track.

## Where local stands today

| Pipeline | Hit@1 | MRR@10 | NDCG@10 | Latency | Cost |
|----------|-------|--------|---------|---------|------|
| Cloud reference — Flash-Lite file_first | **0.78** | — | **0.776** | ~3.3 s | $0.32/100 |
| Local embed (Qwen3-0.6B) + **cloud** Flash-Lite rerank | 0.76 | 0.832 | 0.763 | ~2.5 s | embed $0 |
| **Fully local** — Qwen3-0.6B + Gemma-4 E4B OptiQ rerank | 0.620 | 0.701 | 0.687 | ~5.3 s | $0 |
| Local deterministic (no rerank) | 0.520 | 0.633 | 0.610 | 0.35 s | $0 |
| IntelliJ 1000-case (file-summary-only, local embed) | 0.280 | 0.336 | 0.362 | 41 ms | $0 |

Two gaps to close:
- **Fully-local is ~14 pts behind cloud on Hit@1** (0.62 vs 0.78). The reranker, not the
  embedder, is the binding constraint: local *embeddings* paired with a cloud rerank reach
  0.76, so the embedding floor is fine — **the local rerank stage is what's losing 14 pts.**
- **IntelliJ-scale is broken** (Hit@1 0.28). The reports' own diagnosis: file-summary-only
  index is too coarse — an **index-composition** problem, not an embedding or scale problem.

## The root-cause insight (this reframes everything)

**We are reranking with the wrong *class* of model, on a serving stack that can't run the
right one.**

- The local "rerankers" are **generative instruct models** (Gemma-4, Qwen3.5-instruct) asked
  to emit a JSON ranking. The literature is consistent: dedicated **cross-encoders** match or
  beat generative-LLM rerankers on accuracy *and* are far cheaper/faster.
- A purpose-built cross-encoder reranker exists at exactly our size class: **Qwen3-Reranker
  (0.6B / 4B / 8B)** — MTEB-Code reranking **73.4 / 81.2 / 81.2**, reported to beat
  bge-reranker-v2-m3 and jina rerankers.
- **But Ollama and MLX expose no true cross-encoder rerank endpoint.** Only **llama.cpp
  `/v1/rerank`** (with `pooling=rank` + the classification head) or sentence-transformers
  `CrossEncoder` run a real reranker. Driving Qwen3-Reranker through MLX/Ollama silently
  degrades it to generative behaviour — which is exactly the trap we're in.

This also explains the symptoms in our own reports: the loose-JSON salvage, the
`reasoning_content` leakage, the thinking-mode latency blowups — all are artifacts of
**bending a generative model into a ranker.** A cross-encoder emits a score, not prose, so
those failure modes disappear.

---

## Proposals (prioritized for the local track)

### L1 — Replace the generative reranker with a dedicated cross-encoder (Qwen3-Reranker) ★ headline
**Why:** the single highest-leverage move. The rerank stage is the 14-pt gap; a code-tuned
cross-encoder is built for precisely this and removes the JSON/thinking failure modes.
**What:** add a **cross-encoder rerank provider** (new abstraction, distinct from the
generative path) backed by **Qwen3-Reranker-0.6B** (start) / **4B** (if latency allows). It
emits a relevance score per (query, candidate) pair — no JSON parsing, no `reasoning_content`,
no loose-regex salvage (kills findings P-1/P-3 too).
**Measure:** 100-case Hit@1/NDCG/latency vs the current Gemma-4 E4B OptiQ (0.620/0.687/5.3 s)
and vs cloud Flash-Lite (0.78/0.776). Target: close most of the 14-pt gap at lower latency.
**Effort:** M · **Expected:** the bulk of the gap closed, fully local, with lower latency
than the generative reranker. **Risk:** serving (see L2).

### L2 — Serve the reranker on llama.cpp `/v1/rerank` (not Ollama/MLX) — enabler for L1
**Why:** L1 is worthless on a stack that can't run a cross-encoder. MLX has no rerank head;
Ollama has no rerank endpoint. **llama.cpp `/v1/rerank`** is the only mainstream local stack
with a correct reranking endpoint (sentence-transformers `CrossEncoder` is the Python
alternative).
**What:** stand up a llama.cpp rerank server; point a new `CrossEncoderRerankProvider` at it.
**Critical:** the naive GGUF conversion produces broken ~0 scores — must use `pooling=rank`
and include the classification head (`cls.output.weight`); use a seq-cls checkpoint.
**Measure:** sanity-check scores are non-degenerate before trusting any eval.
**Effort:** S–M · **Risk:** the GGUF-conversion gotcha — verify scores first.

### L3 — Fix IntelliJ-scale: richer index composition, not file-summary-only
**Why:** Hit@1 0.28 is an index-composition failure the reports already diagnosed.
File-summary-only is a known anti-pattern; it can't answer path/symbol/workflow queries
(those buckets scored 0.21/0.21).
**What:** **hierarchical indexing** — keep file/module summaries to prune, but add
function/class **AST chunks + capped JVM symbols + graph neighbors**, then rerank the merged
candidate set (L1). JVM symbol extraction already exists (just fix the J-1 false-symbol regex
first). Use streaming/append indexing — but only after the **I-1W critical bug is fixed**
(partial-write on failure), else large reindexes silently corrupt.
**Measure:** IntelliJ 1000-case Hit@1/NDCG with the richer profile vs 0.28/0.362; watch the
path_symbol bucket specifically.
**Effort:** M–L · **Expected:** large jump from the 0.28 floor; this is the biggest
*absolute* quality opportunity in the repo. **Risk:** index size/time — control with int8/MRL
(L5) and capped symbols.

### L4 — Step up the embedder where it pays (4B for incremental; better 0.5B drop-in)
**Why:** the 0.6B embedder is *adequate* (cloud-rerank reaches 0.76 on top of it), so this is
secondary to L1 — but there's headroom. **jina-code-embeddings-0.5b** reports ~+5 pts
MTEB-Code over Qwen3-0.6B at 20% smaller (drop-in, ships GGUF); **Qwen3-Embedding-4B** is
80.06 vs 75.41 but 6.7× slower to index.
**What:** A/B jina-code-0.5b as a same-size drop-in; reserve 4B for **incremental/changed-file**
indexing where its index-time cost is amortized.
**Measure:** deterministic Hit@10 / top-40 recall (does the recall floor improve?) before
rerank, so the gain is attributable to embeddings.
**Effort:** S (reindex + A/B) · **Expected:** modest recall lift; raises the ceiling L1 reranks
against. **Risk:** dimension/storage — pair with L5.

### L5 — Sane quantization & storage for local scale
**Why:** part of the local shortfall is likely **4-bit weights hurting a small (0.6B)
embedder disproportionately**; and IntelliJ-scale needs compact vectors.
**What:** (a) prefer **8-bit weights for the small embedder** (4-bit is fine for 4B+);
(b) store vectors as **int8 (~1–2% NDCG loss, 4×) or float8 (<0.3%, 4×)** + **MRL truncation
1024→256**; **never binary** as the primary index (≈17% recall loss).
**Measure:** NDCG delta vs full-precision at each step; storage footprint.
**Effort:** S–M · **Expected:** recover quantization-induced loss + make IntelliJ-scale
storage tractable. **Risk:** low; measured per step.

### L6 — Demote the generative reranker; gate the agentic loop
**Why:** generative rerank and the agentic loop (12.9 s/query, the AG-1/AG-2 round-exhaustion
bugs) are expensive and quietly degrade. They have a niche, not the hot path.
**What:** keep a generative/agentic pass **only for the hard tail** — when the cross-encoder's
top-1 confidence (score margin) is low. Fix AG-1/AG-2 (round guard + prefer parsed results +
`degraded` flag) before relying on it.
**Effort:** S–M · **Expected:** keeps the cheap cross-encoder on the hot path; reserves
expensive reasoning for borderline queries. **Risk:** low (gated).

---

## Recommended sequencing

```
L2 llama.cpp /v1/rerank server ──┐ (enabler)
L1 Qwen3-Reranker cross-encoder ─┴─ ★ closes most of the 14-pt rerank gap, fully local
L3 hierarchical IntelliJ index ──── biggest ABSOLUTE win (0.28 → ?), needs I-1W fixed first
L4 embedder A/B (jina-0.5b / 4B) ── secondary recall lift
L5 8-bit weights + int8/MRL vectors ─ recover quant loss + scale storage
L6 demote generative/agentic to the hard tail ── cost/latency hygiene
```

**Do first, regardless:** fix the **I-1W critical** streaming-index partial-write bug
(`AUDIT-2026-06-02.md`) — L3 reindexes IntelliJ-scale corpora and would silently corrupt the
index on any mid-stream failure.

**Headline:** the local gap is mostly a **wrong-reranker-class + wrong-serving-stack** problem,
not an embedding problem. **L1 + L2 (Qwen3-Reranker cross-encoder on llama.cpp)** is the move
that should pull fully-local Hit@1 from 0.62 toward cloud's 0.78 at $0 and lower latency; **L3**
is the largest absolute win for real (IntelliJ-scale) repos.

## External references
Qwen3-Reranker (MTEB-Code 73.4/81.2/81.2; HF Qwen/Qwen3-Reranker-{0.6B,4B,8B}; seq-cls head) ·
Qwen3-Embedding paper arXiv 2506.05176 · jina-code-embeddings arXiv 2508.21290 ·
cross-encoder vs LLM rerank arXiv 2403.10407 · llama.cpp `/v1/rerank` (pooling=rank, cls head) ·
embedding quantization (HF blog; arXiv 2505.00105, 2511.13057) · AST chunking + hierarchical
indexing for large repos.
