# 04 — Hybrid Search

The current research focus. Combines five independent retrieval signals into one ranking.

Files: `strategies/hybrid_retrieval_strategy.py`, `hybrid_candidate_scorer.py`,
`hybrid_candidate_score.py`, `hybrid_query_router.py`, `hybrid_query_analyzer.py`,
`hybrid_lexical_index.py`, `hybrid_item_profiler.py`, `hybrid_item_profile.py`.
Config: `config/hybrid_search_config.py`.

## The five signals

| Signal | Source | Default weight |
|--------|--------|----------------|
| **vector** | Embedding cosine top-k from store | 0.60 |
| **lexical** | BM25 over `hybrid_lexical_index` | 0.18 |
| **path** | Query tokens vs item path | 0.12 |
| **symbol** | Query tokens vs item symbols | 0.05 |
| **graph** | Seed expansion over `CodeGraph` | 0.05 |

Per-item-kind multipliers (chunk / symbol / file_summary) further weight candidates.

### New signal: `symbol_match_score`

An 8th dedicated **symbol-name-match** signal (`symbol_match_score`) with config knob
`HybridSearchConfig.symbol_match_weight` (default `0.0` in `Defaults`). It participates
in **both** weighted and RRF fusion (RRF early-returns when `weight <= 0`, so the default
is a **no-op**).

⚠️ Cross-reference H-2 (AUDIT-2026-06-02): `symbol_match_score` **double-counts** with
the existing `symbol` signal when its weight is raised — both reward symbol-name overlap,
so raising `symbol_match_weight` inflates symbol candidates twice.

## Query routing — `hybrid_query_router.py`

`hybrid_query_analyzer.py` classifies the query (semantic / path / symbol / workflow /
exact); the router picks a weight profile per route.

**Contract (intended)**: weight profiles sum to 1.0 so scores are comparable across
routes.
⚠️ Divergence (R-5): `ROUTE_WORKFLOW` sums to **0.92**, not 1.0. In weighted (non-RRF)
mode these are direct multipliers, so workflow-routed results are silently scaled down
vs other routes — cross-route scores are incomparable. No invariant enforces the sum
(⚠️ 1.2).

## Lexical index — `hybrid_lexical_index.py` + `services/tokenizer.py`

BM25 inverted index built at index time. Tokenizer splits identifiers
(`HybridQueryRouter → hybrid, query, router`) **and** keeps the full token.

⚠️ Divergences:
- (R-7) `_weighted_tokens` **duplicates** title/path/metadata tokens (2×) to boost
  them. This inflates BM25 term frequency non-standardly: title-heavy docs saturate `k1`
  faster, document length normalization is distorted, and the formula no longer matches
  textbook BM25. IDF (from the inverted index) is unaffected; TF is.
- (X-1) The tokenizer emits both the camelCase whole-token and its parts, so a doc is
  indexed under both `hybridqueryrouter` and `hybrid` — double-counting TF for
  identifier-heavy code. Internally consistent but non-standard.

## Candidate scoring — `hybrid_candidate_scorer.py`

Produces a `HybridCandidateScore` (vector/lexical/path/symbol/graph breakdown).

⚠️ Divergence (R-6): `_coverage = matches / len(query.terms)` — fraction of *query*
terms present in the item. This penalizes long queries: 3 matched terms score 1.0 in a
3-term query but 0.3 in a 10-term query for the same item. Not normalized by document
term density; query length dominates match quality.

## Fusion — two modes in `hybrid_retrieval_strategy.py`

### Weighted sum
`HybridCandidateScore.total()` = Σ(signal × weight × kind_multiplier). Sensitive to the
non-unity weight bug (R-5) and to per-query normalization (R-4).

### RRF (Reciprocal Rank Fusion)
`_add_rrf(scores, ranked_ids, weight)` adds `weight / (rrf_k + rank)` per channel.
- `_ranked_ids` filters `value > 0` for lexical/path/symbol/graph (correct).
- ⚠️ (R-2) The **vector** channel is not filtered, so items with `vector_score == 0`
  (never in the vector set) still receive a vector-channel RRF contribution.

## Stage-rank tracing — `hybrid_retrieval_strategy._trace_rank_stages`

`_trace_rank_stages` logs each candidate's rank across **all 8 dimensions**
(vector / lexical / path / symbol / symbol_match / graph / file_vote) for up to 60
candidates. This delivers the previously-proposed "stage-level rank logging" — the
per-stage rank of a candidate is now observable.

⚠️ H-3 (AUDIT-2026-06-02): the trace is sorted by `weighted_total` **even in RRF mode**,
so the logged ordering does not match the actual RRF ranking when RRF fusion is active.

## Normalization — `_normalize`

Min-max over the current query's candidate scores.
⚠️ (R-1) `if high == low: return {id: 1.0 for ...}` — every tied/single candidate
becomes 1.0. Used for both vector seeding and graph seeding; in the degenerate case
every graph neighbor inherits full seed weight regardless of original rank. Correct
degenerate behaviour is to preserve the raw value (or use 0.0 sentinel).
⚠️ (R-4) Vector scores are re-normalized per query, twice (once in `_seed_vector_scores`,
once in `_graph_scores`), destroying cross-query score semantics.

## New config knobs (`config/hybrid_search_config.py`)

Recent experiments added several tuning knobs on `HybridSearchConfig`:

| Knob | Default | Purpose |
|------|---------|---------|
| `vector_kind_limits` | `{}` | Split-vector: absolute per-index-kind vector budgets (see [03](./03-retrieval-strategies.md) `multi_index_vector`) |
| `vector_kind_multipliers` | `{}` | Split-vector: per-kind budgets relative to `candidate_limit` |
| `file_vote_weight` | `0.0` | File-level consensus voting — boost candidates whose file has multiple hits |
| `preserve_vector_top` | `False` | Guard: keep a confident top vector hit at rank-1 instead of letting weak signals demote it |
| `vector_top_score_margin` | `0.0` | Margin used by `preserve_vector_top` to decide "confident" |

⚠️ The scoring-contract findings **R-1 / R-2 / R-4 / R-5 / R-6 / R-7 remain OPEN** — no
golden tests pin the normalization scheme, weight-sum invariant, BM25 variant, or
coverage definition yet. These knobs tune the fusion but do not resolve the underlying
comparability defects.

## Hybrid invariants (intended vs actual)

| # | Intended invariant | Status |
|---|--------------------|--------|
| 1 | Weight profiles sum to 1.0 | ❌ R-5 (workflow=0.92), unenforced |
| 2 | A channel only scores items present in that channel | ❌ R-2 (vector channel leaks zeros) |
| 3 | Scores comparable across queries/routes | ❌ R-4, R-5 — ordinal only |
| 4 | BM25 is standard BM25 | ⚠️ R-7, X-1 — non-standard TF |
| 5 | Coverage rewards match quality, not query length | ❌ R-6 |
| 6 | Thread-safe lazy caches | ❌ X-2 — no locking |

This subsystem carries the **highest concentration of correctness/quality findings** and
is exactly where retrieval-quality regressions originate. It is tested only at the
behavioural level (⚠️ 3.2): the normalization edge case, RRF path, and BM25/coverage
mode switch are untested.
