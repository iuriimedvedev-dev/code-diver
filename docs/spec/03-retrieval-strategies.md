# 03 — Retrieval Strategies

A `RetrievalStrategy` maps a query string to a ranked list of `SearchResult`s.

Contract: `strategies/retrieval_strategy.py`
```python
class RetrievalStrategy(ABC):
    def search(self, query: str, limit: int) -> list[SearchResult]: ...
```
Selected at runtime by `strategies/retrieval_strategy_factory.py` from
`search.strategy` (ids in `settings/retrieval_strategy_id.py`).

`RetrievalStrategyFactory` validates `search.strategy` against `RetrievalStrategyId`.
Invalid strategy ids now fail fast instead of silently falling back to vector search.

## Strategy catalogue

| Id | File | Idea |
|----|------|------|
| `vector` | `vector_retrieval_strategy.py` | Embed query, cosine top-k from store |
| `recursive` | `recursive_retrieval_strategy.py` | retrieve → read → extract refs → re-query, N rounds |
| `graph` | `graph_retrieval_strategy.py` | Vector seed → expand graph neighbors |
| `hybrid` | `hybrid_retrieval_strategy.py` | Fuse vector + lexical + path + symbol + graph |
| `multi_index_vector` | `multi_index_vector_retrieval_strategy.py` | Split-vector: partition vector search per index kind, dedup + re-rank |
| `hybrid_rerank` | `llm_rerank_retrieval_strategy.py` | H3 hybrid candidates -> one bounded LLM rerank call; H5 default |
| `cross_encoder_rerank` | `cross_encoder_rerank_retrieval_strategy.py` | Hybrid candidates -> dedicated rerank endpoint |
| `orchestrated` | `orchestration/orchestrated_retrieval_strategy.py` | LLM plans which strategy/tool to use |

## vector

Baseline. Embed query, query store, return top-k. **No tracing** of the call
(⚠️ 4.2) — for a benchmarking tool this hot path is unobservable.

## recursive

Multi-round expansion: retrieve, read top-k, extract referenced symbols/paths, build
expanded queries, repeat for `recursive_search.rounds`.

**Contract**: each round should diversify from the *current* expanded query (depth-first).
⚠️ Divergence (R-10): `_expand_query` is always anchored on the **original** `query`,
not `current_query` — every branch in round 3+ stays pinned to the original, capping
the recall benefit of deeper recursion.

## multi_index_vector (split-vector retrieval)

`multi_index_vector_retrieval_strategy.py` (commit `2ac4147`). Instead of one global
vector top-k, it **partitions vector search per index kind** so that one kind (e.g.
structural chunks) cannot dominate the top results.

- Per-kind budgets via `HybridSearchConfig.vector_kind_limits` (absolute counts) or
  `vector_kind_multipliers` (relative to `candidate_limit`).
- Dedups results by `id`, then re-ranks by `score` + `path`.
- Backed by a new `VectorStore.search_by_index_kind()` (JSON brute-force + native Qdrant
  filter).

**Goal:** stop structural chunks from dominating rank-1.
**Eval:** improved Hit@10 0.87 → 0.91 and lifted the structural-chunk Hit@1 regression
from −0.11 to −0.05, but still below the plain-vector baseline.

## graph

Vector seed set → `GraphCandidateExpander` traversal with typed-edge weights and
per-hop decay (see [05](./05-graph.md)).

⚠️ Divergence (R-11): `_load_graph` does **not** guard `graph_store.exists()` — raises
if the graph artifact is absent. `HybridRetrievalStrategy` handles the same condition
by returning `None` and degrading gracefully. Inconsistent error contracts for one
condition.

## hybrid — see [04](./04-hybrid-search.md) for full scoring spec

Combines five signals via either weighted sum or Reciprocal Rank Fusion (RRF).

⚠️ Key divergences:
- (R-1) `_normalize` returns `1.0` for *all* items when `high == low` (single result or
  ties), inflating graph-expansion seeds and breaking cross-query comparability.
- (R-2) Vector-channel RRF includes items with `vector_score == 0` (lexical/graph-only
  candidates that were never in the vector set), giving them an unearned vector
  contribution.
- (R-4) Vector scores are min-max normalized per query — score `1.0` in one query is a
  weaker match than `0.8` in another. `score` is ordinal-only.
- (X-2) Instance caches (`_item_profiles`, `_lexical_index`, `_graph`,
  `_neighbor_index`) are lazily built with **no locking** — racey under concurrent
  `search`.

## hybrid_rerank / H5

Wraps `hybrid`: take deterministic H3 candidates, ask the LLM to select/order the final
top results, then append non-selected candidates in original order. This is the product
default quality path (H5): local Qwen file-metadata index, H3 candidate generation, and
Gemini 3.1 Flash Lite top-10 ranking unless config overrides it.

**Contract (intended fail-fast)**: a rerank failure should be *observable* — the caller
must be able to tell "reranked" from "fell back".
Current implementation traces `llm_rerank_error` and falls back to deterministic
candidates. Evaluation reports must treat excessive rerank failures/degraded cases as an
invalid quality run, because fallback metrics are not equivalent to a healthy H5 run.

Index handling (R-9): 1-based LLM indices are correctly converted to 0-based; no live
off-by-one, but bounds checks against `len(candidates)` are absent (defensive gap).

## orchestrated

`orchestration/orchestrated_retrieval_strategy.py`: an LLM query plan selects the
sub-strategy/tool, results are merged with `max()` over a `defaultdict(float)`.
⚠️ Divergence (X-3): `defaultdict(float)` seeds missing scores to `0.0`; if a base
strategy ever returns a negative cosine score, the real minimum is masked.

### Adaptive / agentic mode — `DirectSearchOrchestrator` (commit `583663f`)

For hypotheses whose name contains `"adaptive"` / `"agentic"` / `"deep"`, the
orchestration loop becomes **agentic**: it enforces **≥2 candidate-producing tool calls**
and a **forced rerank** before accepting final results, and recursively collects
candidates from `code_diver_inspect` `sections[].result.candidates` (last 200, deduped).

⚠️ Cross-reference AUDIT-2026-06-02:
- **AG-1** — round-budget exhaustion (the ≥2-call + forced-rerank requirement can burn
  the round budget before producing usable results).
- **AG-2** — zero-candidate stall (the loop can stall when no tool yields candidates).
- **AG-3** — substring detection of the mode (`"adaptive"`/`"agentic"`/`"deep"` matched
  as a raw substring of the hypothesis name, not a typed flag).

**Eval (10-case smoke):** Hit@1 0.70, MRR 0.775, 12.9 s/query, $0.062 — too
slow/expensive as a default; use only for hard queries.

## Shared invariants (intended)

1. Return at most `limit` results, best-first.
2. Empty index / empty candidates ⇒ empty list, never an exception.
3. Failures are surfaced, not silently absorbed. ⚠️ Violated by R-8, R-11.
4. Determinism: same index + query + config ⇒ same ranking. ⚠️ Threatened by R-1/R-4
   (per-query normalization) and any LLM-in-the-loop strategy.
