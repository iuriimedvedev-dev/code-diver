# Assignment Plan And Progress

This document maps the implementation to the Applied Research Division assignment: a local code exploration AI assistant with indexing, search, evaluation, documentation, and experiment analysis.

## Scope

Target repositories:

| Repository | Role | Languages |
| --- | --- | --- |
| `../protogen` | Main development and fast evaluation target. | Python, YAML, frontend metadata |
| `../intellij-community` | Large-repository stress target. | Java, Kotlin, XML, Gradle, YAML |

Core CLI:

| Command | Status | Notes |
| --- | --- | --- |
| `index` | Done | Builds deterministic code items, embeddings, Qdrant/JSON artifacts, and optional graph artifacts. |
| `search` | Done | Returns colored, syntax-highlighted, file-linked results with snippets and editor opening support. |
| `evaluate` | Done | Runs JSONL datasets and reports retrieval quality, file-level metrics, latency, and bucket diagnostics. |
| `experiment` | Done | Runs configured retrieval hypotheses from YAML and can record metrics. |

## Time Plan

| Stage | Estimate | Actual status |
| --- | ---: | --- |
| Read assignment and define scope | 30 min | Done |
| CLI skeleton and config model | 45 min | Done |
| Code scanner and index storage | 1 h | Done |
| Embedding providers and Qdrant integration | 1 h | Done |
| Search UI and read-only tools | 45 min | Done |
| Evaluation dataset and metrics | 1 h | Done |
| Experiments and model comparison | 1-2 h | Done and ongoing |
| Documentation cleanup | 45 min | In progress |

The implementation exceeded the original 4-6 hour assignment scope because it also explores large-repository indexing, local/API model tradeoffs, GraphRAG, cross-encoder reranking, and detailed metrics.

## Design Decisions

1. **Config-first CLI.** YAML owns providers, model names, storage, scanner settings, retrieval strategy, graph settings, and experiment hypotheses.
2. **Provider-agnostic interfaces.** Gemini, Vertex, OpenAI, OpenAI-compatible local servers, hash embeddings, and llama.cpp rerankers are selected by config rather than hardcoded in search logic.
3. **Deterministic indexing first.** The active quality path uses deterministic scanning, symbols, structural chunks, file summaries, and optional graph edges. LLMs are reserved for reranking, verification, and hard-case search.
4. **Local Qdrant for serious runs.** JSON storage remains useful for small deterministic tests, but Qdrant is the default for large and repeated experiments.
5. **Evaluation is first-class.** Every model/indexing idea is expected to produce Hit@1, Hit@3, Hit@5, Hit@10, MRR, nDCG, MAP, file-level metrics, latency, and cost where applicable.

## Model Choices

| Role | Main candidates | Current finding |
| --- | --- | --- |
| Local embeddings | Qwen3 Embedding 0.6B/4B 4-bit | 0.6B is the best practical local default; 4B improves raw recall but is much slower to index. |
| API embeddings | Gemini Embedding 001, 3072 dims | Best measured raw candidate generator so far. |
| Local rerank | Qwen3-Reranker 0.6B/4B via llama.cpp `/v1/rerank` | Dedicated cross-encoder rerank is cleaner than using a generative JSON judge. 4B is under test. |
| API rerank | Gemini Flash Lite | Best measured quality/cost balance so far. |
| Generative local judge | Gemma E4B OptiQ, Gemma E2B, Qwen3.5 4B | Useful as a hard-case fallback, not ideal as the always-on reranker. |

## Evaluation Datasets

| Dataset | Cases | Target |
| --- | ---: | --- |
| `datasets/protogen_eval.jsonl` | 10 | Smoke and e2e checks. |
| `datasets/protogen_eval_100.jsonl` | 100 | Main fast quality benchmark. |
| `datasets/intellij_eval_1000.jsonl` | 1000 | Large-repository stress benchmark. |

## Current Best Results

Protogen 100, fresh API quality run:

| Pipeline | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Mean latency | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini Embedding 3072 + hybrid | 0.61 | 0.83 | 0.87 | 0.92 | 0.724 | 0.693 | 560ms | ~$0.184 index |
| Gemini Embedding 3072 + Gemini compact rerank | 0.73 | 0.87 | 0.91 | 0.93 | 0.800 | 0.764 | 1503ms | +~$0.132/100 queries |
| Gemini Embedding 3072 + Gemini file-first rerank | 0.76 | 0.91 | 0.92 | 0.94 | 0.834 | 0.778 | 2536ms | +~$0.314/100 queries |

Protogen 100, local comparison already completed:

| Pipeline | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | nDCG@10 | Mean latency | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3 Embedding 0.6B + hybrid | 0.52 | 0.72 | pending older run | 0.86 | 0.634 | 0.607 | 318ms | $0 |
| Qwen3 Embedding 0.6B + Gemini file-first rerank | 0.76 | 0.90 | pending older run | 0.94 | 0.832 | 0.763 | 2523ms | ~$0.312/100 queries |
| Qwen3 Embedding 0.6B + Qwen3-Reranker 0.6B | 0.59 | 0.73 | 0.77 | 0.88 | 0.673 | 0.656 | 2182ms | $0 |
| Qwen3 Embedding 0.6B + Gemma E4B OptiQ rerank | 0.62 | 0.73 | 0.84 | 0.89 | 0.701 | 0.685 | 5955ms | $0 |

IntelliJ 1000 baseline:

| Pipeline | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3 Embedding 0.6B file-summary-only hybrid | 0.280 | 0.380 | 0.444 | 0.336 | 0.362 | 40.8ms |

The IntelliJ baseline is intentionally under-indexed. The prepared quality config is `configs/intellij-community-hybrid-quality.yml`.

## Progress Log

| Date | Progress |
| --- | --- |
| 2026-05-31 | Implemented initial CLI, code scanning, retrieval, eval datasets, and local/API provider configs. |
| 2026-06-01 | Added Qdrant, hybrid scoring, GraphRAG, direct tool evaluation, traces, metrics docs, and Protogen 100-case benchmarking. |
| 2026-06-02 | Added Hit@5, prompt tracing, staged Qdrant replacement, llama.cpp cross-encoder rerank provider, IntelliJ 1k dataset setup, and fresh Gemini 3072 API quality run. |
| 2026-06-02 | Started local `Qwen3-Embedding-4B + Qwen3-Reranker-4B` experiment, stopped heavy eval, and fixed system issues found during debugging: cross-encoder `candidate_limit`, hypothesis override inheritance, experiment runner rerank overrides, and parallel evaluation workers. |

## Known Gaps

1. README should be tightened for assignment review: quickstart, target repo, sample search, and evaluation commands should be easier to scan.
2. IntelliJ quality index has been prepared but not fully evaluated yet.
3. Ensemble retrieval across two or more independent embedding indexes is not implemented yet; current hybrid retrieval combines multiple item kinds/signals inside one vector collection.
4. Local Qwen3-Reranker 4B must be re-run after the debug fixes with a short-list cascade (`candidate_limit: 3/5/10`) and isolated llama.cpp microbenchmarks.
5. Some research/audit docs are extensive and should be summarized for the final submission.

## Reproducible Commands

Fast Protogen run:

```bash
uv sync
uv run code-diver --config configs/protogen-ollama-qdrant.yml index
uv run code-diver --config configs/protogen-ollama-qdrant.yml search "where is the indexing pipeline"
uv run code-diver --config configs/protogen-ollama-qdrant.yml experiment --json
```

API quality run:

```bash
uv run python scripts/benchmark_generation_models.py \
  --suite configs/protogen-gemini-api-embedding-3072-api-rerank.yml
```

Local Qwen4B experiment:

```bash
uv run code-diver --config configs/protogen-qwen4b-embedding-qwen4b-reranker.yml index
uv run code-diver --config configs/protogen-qwen4b-embedding-qwen4b-reranker.yml experiment \
  --hypothesis qwen4b_embedding_hybrid \
  --hypothesis qwen4b_embedding_qwen4b_cross_encoder_top5 \
  --json
```

IntelliJ 1k dataset check:

```bash
uv run python scripts/generate_intellij_eval.py \
  --root ../intellij-community \
  --output /private/tmp/intellij_eval_check.jsonl \
  --limit 1000
```
