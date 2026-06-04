# 00 — System Overview

## Purpose

Code Diver is a **reproducible benchmarking platform for code retrieval**. Given a
repository and a labelled eval dataset (query → expected files/symbols), it answers:
*which combination of indexing mode + retrieval strategy + provider produces the best
retrieval metrics?*

Behaviour is **entirely YAML-driven** (`code-diver.yml` / `configs/*.yml`). Swapping
Gemini ↔ Vertex ↔ OpenAI, JSON ↔ Qdrant, or vector ↔ hybrid ↔ graph requires **no code
change** — only config.

## Scope

| In scope | Out of scope |
|----------|--------------|
| Index one repo at a time | Multi-repo federation |
| Vector / lexical / graph / hybrid retrieval | Real-time / incremental indexing (see ⚠️ I-3) |
| LLM-driven indexing & search orchestration | Being a foundation model (uses external LLMs) |
| Reproducible eval metrics + traces | Persistent user sessions / web UI |
| Optional interactive Pi backend | Production serving |

## Top-level layout

```
src/code_diver/
  cli.py                  # 13-subcommand entry point + (today) eval business logic
  domain/                 # CodeItem, SearchResult, EvalResult, CodeSymbol, edges
  config/                 # ~18 typed config dataclasses
  settings/               # defaults.py, enums (provider ids, strategy ids, env vars)
  services/               # indexing, scanning, embedding, retrieval, evaluation
  strategies/             # retrieval strategies + hybrid scoring pipeline (24 files)
  providers/ generation/  # embedding & generation provider adapters + factories
  store/                  # JSON + Qdrant vector stores
  graph/                  # CodeGraph, builder, AST/containment edges
  ai_indexing/            # LLM-guided index candidate discovery
  orchestration/          # LLM index/query planning
  agent/                  # DirectSearch/Indexing orchestrators, tool executor
  inspection/             # tree/grep/rg/symbols/read + path guard + ignore matcher
  metrics/                # ClickHouse client + repository + writers
  experiments/            # ExperimentRunner, run/result dataclasses
  tracing/                # TraceLogger (JSONL)
  ui/                     # rich rendering, editor opener
  pi/                     # Pi (TypeScript agent) launcher integration
  plugins/                # plugin hook manager
tests/                    # unit / smoke / e2e (101 tests)
configs/ + *.yml          # 13+ experiment configs
ops/ docker/              # ClickHouse+Grafana stack, container image
docs/                     # architecture/research/metrics notes
```

Stack: **Python 3.10+** (hatchling build, `uv` lockfile), TypeScript Pi extension,
YAML config. Runtime deps: `google-genai`, `qdrant-client`, `PyYAML`, `rich`.

## Five operating phases

1. **Index** (`index`, `index-selected`): scan → extract `CodeItem`s (chunk / symbol /
   file-summary) → embed → persist vectors (+ optional graph). See [02](./02-indexing.md).
2. **Retrieve** (`search` / internal): embed query → run a `RetrievalStrategy` → ranked
   `SearchResult`s. See [03](./03-retrieval-strategies.md).
3. **Evaluate** (`evaluate`): run eval cases through a strategy, compute hit@k / MRR /
   P@k / R@k / NDCG / AP, bucket by query type. See [08](./08-evaluation-and-experiments.md).
4. **Orchestrate** (`evaluate-indexing`, `evaluate-search-tools`): multi-round LLM agent
   loops over inspection tools. See [06](./06-agent-orchestration.md).
5. **Interact** (`ask`, `chat`): optional Pi backend; not part of reproducible evals.

## Core data flow

```
            ┌─────────────┐
 code-diver.yml ─▶ AppConfig (ConfigLoader)
            └─────────────┘
                   │
   ┌───────────────┼────────────────────────────┐
   ▼               ▼                             ▼
IndexingService   RetrievalStrategyFactory   EvaluationService / ExperimentRunner
   │               │                             │
 Scanner          VectorRetrieval               loads EvalCase dataset
 (scanner/ai/     RecursiveRetrieval            runs strategy per case
  orchestrated)   GraphRetrieval                computes metrics
   │               HybridRetrieval ─┐            writes to ClickHouse
 EmbeddingProvider LlmRerank        │            + TraceLogger JSONL
   │               OrchestratedRetrieval
 VectorStore      │
 (json/qdrant)    └─ uses VectorStore + EmbeddingProvider + (CodeGraph)
   │
 CodeGraphBuilder (optional) ─▶ CodeGraphStore
```

## Architectural principles claimed

The repo advertises "screaming architecture, SOLID, fail-fast, no magic values". The
specs below treat these as the **intended contract**. The audit measures how far
reality is from them — notably:
- `cli.py` (1,041 lines) holds evaluation business logic, breaking the boundary it
  names (⚠️ Finding 5.1).
- "No magic values" is violated by `1_000_000` repeated in 8+ constructors (⚠️ 1.3) and
  hardcoded prices/weights.
- "Fail-fast" is contradicted by broad `except Exception` swallowing and silent
  fallbacks across orchestration and retrieval (⚠️ A-1, R-8, I-4).

See [`AUDIT.md`](./AUDIT.md) for the full picture.
