# Code Diver — Specification Backbone

**Last updated:** 2026-06-02 (post audit-remediation + structural/split-vector/Flash-Lite-rerank work + local-model (Qwen3 embeddings / Gemma-4 rerankers) work; see AUDIT-2026-06-02.md).

This folder is the **as-built specification** of Code Diver, reverse-engineered from
the source on 2026-06-01. It exists to give the project a stable backbone to review
against: each spec states what a subsystem *is supposed to do* (contract + invariants),
points at the implementing files, and flags where the implementation diverges from the
contract.

> These specs describe the code **as it exists today**, not an aspirational design.
> Every "⚠️ Divergence" note links to a finding in [`AUDIT.md`](./AUDIT.md).

## What Code Diver is

A **config-first codebase RAG research sandbox**. It indexes a single repository,
retrieves code with pluggable strategies, and benchmarks retrieval quality with
reproducible metrics. It is **not** a production assistant, web service, or model — it
orchestrates external LLMs (Gemini / Vertex / OpenAI-compatible) and vector stores
(JSON / Qdrant) to run *experiments* about how to search code well.

Primary value: **measure, with traces and metrics, which indexing + retrieval strategy
wins on a labelled eval dataset.**

## Spec index

| # | Spec | Scope |
|---|------|-------|
| 00 | [overview](./00-overview.md) | Purpose, scope, top-level architecture, data flow |
| 01 | [domain-model](./01-domain-model.md) | CodeItem, SearchResult, EvalResult, CodeSymbol, CodeGraph |
| 02 | [indexing](./02-indexing.md) | Scan → chunk → embed → store; scanner/ai/orchestrated modes |
| 03 | [retrieval-strategies](./03-retrieval-strategies.md) | vector / recursive / graph / hybrid / llm-rerank / orchestrated |
| 04 | [hybrid-search](./04-hybrid-search.md) | Scoring signals, BM25, fusion, routing |
| 05 | [graph](./05-graph.md) | Edge kinds, graph builder, neighbor expansion |
| 06 | [agent-orchestration](./06-agent-orchestration.md) | Direct search/indexing orchestrators, tools, budgets |
| 07 | [providers-and-storage](./07-providers-and-storage.md) | Embedding/generation providers, vector stores |
| 08 | [evaluation-and-experiments](./08-evaluation-and-experiments.md) | Metrics, datasets, experiment runner, ClickHouse |
| 09 | [configuration](./09-configuration.md) | Config dataclasses, defaults, env, CLI |
| — | [AUDIT.md](./AUDIT.md) | **What we do wrong** — ranked findings + remediation roadmap |

## How to read this for review

1. Start with [`AUDIT.md`](./AUDIT.md) — the ranked list of problems and the verdict.
2. For any finding, jump to the relevant spec to see the intended contract it violates.
3. Use the specs as acceptance criteria when fixing: a fix is "done" when the
   implementation matches the contract and the ⚠️ note can be removed.
