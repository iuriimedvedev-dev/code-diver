# 2026-09-01 — H-84: multi-query expansion + RRF fusion

## Hypothesis

WHERE-style queries ("where is extract method refactoring implemented") are vague while the
indexed file summaries are dense and technical; a single embedding of the raw question loses
recall. Retrieve with several query variants in parallel and fuse per-file ranked lists with
reciprocal rank fusion. Principle already validated by the fan-out agent (0.618 vs 0.576
single-pass, H-75/H-76).

## Design decisions

- **New wrapper strategy, zero changes to existing strategies** (parallel-work constraint):
  `src/code_diver/strategies/multi_query_rrf_strategy.py` wraps whatever the factory built.
  `RetrievalStrategyFactory.create` became `_create_base`; the new `create` wraps it with
  `MultiQueryRrfStrategy` only when `multi_query.enabled`. Disabled = the factory returns the
  base strategy object unchanged — bit-exact current behavior for every existing config.
- **Fusion point**: v1 fans out the FULL pipeline (retrieval + cross-encoder rerank) per
  variant and fuses at the very end. Simple and correct, but each variant pays a full CE pass:
  compute cost is up to `max_variants`× (4× default); wall-clock is bounded by
  `max_variant_workers` threads (same `ThreadPoolExecutor` pattern as `FanOutUnionRerankSearch`
  and `DualCollectionVectorRetrievalStrategy`; the underlying pipeline is HTTP-bound and
  already used thread-parallel by H-75/H-76). Expect roughly 1.5–2.5× wall-clock per query
  with 4 workers. A later arm can move fusion before the CE (single CE pass over the union,
  H-76 style) if latency matters.
- **RRF**: `score(path) = Σ w_i / (rrf_k + rank_i(path))`, rank = first occurrence of the path
  in variant i's list (duplicates within one list count once). Original query is always
  variant 0 with `original_query_weight` (2.0); every rewrite weighs 1.0. Ties broken by the
  representative's raw underlying score (epsilon `raw * 1e-9`, same idiom as H-73 dual
  collection), then path.
- **Deterministic, LLM-free variants** (reproducible, no model needed):
  1. *statement*: strip interrogative scaffolding (`where/how/what/... + is/are/does/... +
     optional "i find" + article`) and trailing scope ("in the codebase/code/project/ide").
  2. *aliased*: curated ~30-entry IDE/code-search dictionary applied on word boundaries,
     longest phrase first (verb→noun normalization `implemented→implementation`,
     `managed→management`, …; domain bridges `find usages→usage search`,
     `go to declaration→navigate to declaration`, `code folding→collapse regions`,
     `settings→options`, `keymap→keyboard shortcut`, `debugger→debug`, `vcs↔version control`,
     `search everywhere→SearchEverywhere`, …). Built from WHERE-79 vocabulary but generic —
     no gold-answer paths encoded.
  3. *camelCase symbol guess*: content words minus filler/generic verbs, first 4, joined:
     "extract method refactoring implemented" → `ExtractMethodRefactoring`.
  Variants are deduped case-insensitively, original always first, capped at `max_variants`
  (total, original included). If only the original survives, search is a pure passthrough.
- **Optional LLM hook, default OFF**: `llm_rewrites_enabled` builds an `LlmQueryRewriter` on
  the configured generation provider (`generate_json` + schema, failures degrade to the
  deterministic set). The deterministic path never touches a model.

## Flags (`multi_query` section, loader follows the `fan_out_fusion` base-default pattern)

| flag | default | meaning |
|---|---|---|
| `enabled` | `false` | OFF = factory returns the base strategy unchanged |
| `max_variants` | `4` | total queries run, original included |
| `rrf_k` | `60` | RRF constant |
| `original_query_weight` | `2.0` | RRF weight of variant 0 (rewrites weigh 1.0) |
| `llm_rewrites_enabled` | `false` | optional model rewrites to fill remaining variant slots |
| `parallel_variants` | `true` | thread-parallel variant searches |
| `max_variant_workers` | `4` | thread cap |

## Files

- NEW `src/code_diver/config/multi_query_config.py`, `src/code_diver/strategies/multi_query_rrf_strategy.py`
- NEW `configs/intellij/intellij-h84-multiquery.yml` = champion H-66b copy + `multi_query` enabled, suite `h84-multiquery` (same collection `intellij_h66b_budget_qwen` — variants hit the same index)
- NEW `tests/unit/test_multi_query_rrf_strategy.py` (8 tests: RRF math, original weight, passthrough, factory wrap/no-wrap, loader, deterministic rewrites, parallel==sequential, per-list dedup)
- WIRED `retrieval_strategy_factory.py` (`create` → `_create_base` + wrap), `app_config.py`, `config_loader.py`, `config/__init__.py`, `strategies/__init__.py`

## Example expansion

`where is the extract method refactoring implemented` →
`[original, "extract method refactoring implemented", "extract method refactor implementation", "ExtractMethodRefactoring"]`

## Validation

`uv run --no-sync pytest tests/unit`: 1355 passed, 1 failed — `test_validate_eval_dataset.py`
fails identically on a clean tree (pre-existing, unrelated). Ruff clean on all touched files.

## Next steps

- Run the WHERE-79 + 1065 eval with `configs/intellij/intellij-h84-multiquery.yml` vs champion.
- If recall gains hold but latency hurts, try the H-76-style variant: fan out the CE-less base,
  fuse the union, single CE pass (`union_rerank` analogue inside the wrapper).
- Sweep `original_query_weight` (1.0/1.5/2.0/3.0) and `max_variants` (3/4/6).
