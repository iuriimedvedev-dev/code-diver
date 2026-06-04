# 08 — Evaluation & Experiments

The reason the project exists: measure retrieval quality reproducibly and compare
hypotheses.

Reusable hypothesis documentation lives in [`../hypotheses/`](../hypotheses/README.md).

Files: `services/evaluation_service.py`, `services/dataset_loader.py`,
`services/eval_case_bucket_classifier.py`, `math_utils.py`, `experiments/*`,
`metrics/*`. Entry: `cli.py` `cmd_evaluate`, `cmd_evaluate_indexing`,
`cmd_evaluate_search_tools`, `cmd_experiment`.

⚠️ **Boundary violation (5.1, High)**: a large amount of evaluation *business logic*
(`direct_search_ndcg`, `direct_search_average_precision`, `mean`, `percentile`,
`eval_result_to_json`, `experiment_run_to_json`, `make_graph_indexer`,
`config_for_indexing_hypothesis`) lives in **`cli.py`** (1,041 lines), not in dedicated
services. The eval harness is effectively implemented in the argument-parser module.

## Datasets — `services/dataset_loader.py`

JSONL eval cases (`datasets/sample_eval.jsonl`, `protogen_eval*.jsonl`). Each case:
query + expected targets + (derived) bucket.

New datasets: `datasets/protogen_eval_30.jsonl` (quick local tuning) and
`datasets/intellij_eval_1000.jsonl` (large-scale / IntelliJ).

## Current results — `protogen_eval_100` (2026-06-01)

| Hypothesis | Hit@1 | Hit@10 | MRR@10 | NDCG@10 | Latency | Cost / 100 |
|------------|-------|--------|--------|---------|---------|-----------|
| `vector_qdrant` (control) | 0.64 | 0.88 | 0.720 | 0.679 | 37 ms | $0 |
| `hybrid_candidates_routed_vector_guard` (best deterministic) | 0.64 | 0.90 | 0.734 | 0.692 | 135 ms | $0 |
| `hybrid_rerank_flash_lite_top20_compact` (best value) | 0.78 | 0.91 | 0.835 | 0.763 | 2.2 s | $0.135 |
| `hybrid_rerank_flash_lite_file_first` (best quality) | 0.78 | 0.93 | 0.842 | 0.776 | 3.3 s | $0.325 |

## Local-model results (2026-06-02)

- **Best local embedder**: `Qwen3-Embedding-0.6B-4bit-DWQ` — deterministic Hit@1 0.52;
  **with** cloud Flash-Lite `file_first` rerank: Hit@1 0.76, MRR 0.832, NDCG 0.763,
  ~2.5 s, $0 embed. (The 4B variant ties on Hit@1 but is **6.7× slower to index** and
  slightly worse reranked.)
- **Best fully-local pipeline**: Qwen3-0.6B embed + Gemma-4 E4B OptiQ 4-bit reranker
  (512 tok, thinking off) — 100-case Hit@1 0.620, MRR 0.701, NDCG 0.687, ~5.3 s/query,
  $0. (30-case: Hit@1 0.667, NDCG 0.764.)
- **Cloud reference** (Flash-Lite `file_first`): Hit@1 0.78, NDCG 0.776. Fully-local is
  ~14 pts behind on Hit@1 and ~9 pts on NDCG — at **$0 and offline**.
- **IntelliJ 1000-case** (file-summary-only, 74.9k items, Qwen3-0.6B local): Hit@1 0.280,
  NDCG 0.362, 41 ms. Diagnosed as an **index-composition problem** (file-summary-only is
  too coarse), **not** an embedding or scale problem.

These delivered the previously-open "hard-negative / larger eval set + stage-level rank
logging" items **partially**: bigger eval sets and a per-stage rank trace (see
[04](./04-hybrid-search.md) `_trace_rank_stages`) now exist.

## Metrics — `math_utils.py` + `EvaluationService`

Per case: `hit@k`, `reciprocal_rank` (→ MRR), `precision@k`, `recall@k`, `NDCG`,
`average_precision` (→ MAP). Bucketed by `eval_case_bucket_classifier.py`
(semantic / path / symbol / workflow / exact).

**New metrics-schema fields:**
- `top_result_kind.<kind>.rate` — which index kind dominates rank-1.
- `first_relevant_kind.<kind>.rate` — which kind produces the first hit (symbols =
  **53.4%** of first hits).
- `llm_rerank_response.total_tokens`, `llm_rerank_response.estimated_cost` — rerank
  token/cost accounting.

`EvaluationService` now matches expected symbol results on the `::` scope operator in
addition to `#` and path prefixes.

**Contract**: metrics are deterministic given a fixed index + strategy + dataset.
⚠️ Threatened by per-query score normalization (R-1, R-4) and any LLM-in-the-loop
strategy (`llm_rerank`, `orchestrated`, AI/orchestrated indexing) — these are not
bit-reproducible. The `hash` embedding + JSON store path **is** reproducible and is the
intended deterministic baseline.

## Experiment runner — `experiments/`

| Component | Role |
|-----------|------|
| `experiment_runner.py` | Runs each hypothesis (strategy/config variant) over the dataset, collects metrics |
| `experiment_run.py` | run_id, suite, per-strategy results |
| `strategy_experiment_result.py` | strategy name, metric dict, per-case results |

Hypotheses are declared in `experiments_config.py` / the YAML `experiments` block.
⚠️ `ExperimentRunner` has **no direct unit test** (⚠️ 3.1) despite being the comparison
engine.

## Metrics persistence — `metrics/` (ClickHouse)

| Component | Role |
|-----------|------|
| `clickhouse_client.py` / `clickhouse_docker_client.py` | HTTP query / local container mgmt |
| `clickhouse_metrics_repository.py` | Store/retrieve experiment metrics |
| `clickhouse_writer.py` | Row inserts |
| `metric_row.py` / `case_metric_row.py` | Row dataclasses |
| `experiment_metrics_mapper.py` | `ExperimentRun` → rows |

Visualized by `ops/metrics/grafana/dashboards/code-diver-rag-evals.json`.

⚠️ (1.5) ClickHouse credentials are hardcoded (`code_diver`) with no env override.
⚠️ (3.1) The ClickHouse client/writer/repository are untested.

## Two trace systems (observability gap) — see [09](./09-configuration.md) & AUDIT 4.1

- `tracing/trace_logger.py` — key `"timestamp"`, config-driven (`TraceConfig`), used by
  indexing / llm_rerank / orchestration.
- `agent/direct_agent_logger.py` — key `"ts"`, raw `Path`, used by direct orchestrators.

Structurally identical, schema-incompatible, neither uses stdlib `logging`. Any eval
dashboard must parse both schemas.
⚠️ **(4.2)** The core retrieval hot paths (`vector`, `recursive`, `hybrid`) and all
embedding calls emit **no trace events** — for a benchmarking tool, the most-used paths
are unobservable.

## Open weaknesses (2026-06-01)

- Workflow-bucket Hit@1 is still ~0.56 — the hardest bucket.
- **6% of cases never reach the top-40 candidate set** — a retrieval/indexing **recall**
  gap that reranking cannot fix.
- Deterministic Hit@1 has **plateaued at 0.64**; only the LLM rerank lifts it (to 0.78).
- The embedding model is still **generic, not code-aware** — the prefix plumbing (T0) is
  in place but no code-specialized model has been swapped in.

## Eval invariants (intended vs actual)

| # | Intended | Status |
|---|----------|--------|
| 1 | Deterministic baseline (hash+json) | ✅ |
| 2 | Eval logic lives in services, not CLI | ❌ 5.1 |
| 3 | One unified, schema-stable trace format | ❌ 4.1 |
| 4 | Retrieval path fully traced | ❌ 4.2 |
| 5 | Comparison engine tested | ❌ 3.1 (ExperimentRunner untested) |
