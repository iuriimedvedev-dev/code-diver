# H13 - Agentic GraphRAG + Documentation Context

| Field | Value |
| --- | --- |
| ID | `H13` |
| Status | active experiment |
| Motivation | H12B improved candidate retrieval with a documentation lane, but final answer judge quality dropped, especially citation quality. H13 keeps the stronger locator and adds the agentic query-planning/shared-rerank branch plus a stricter code-first answer prompt. |
| Assumptions | LLM-generated complementary search probes can improve candidate recall for informal repository questions, while one shared rerank over the merged pool can reduce per-query rerank noise. The answer prompt must treat docs as orientation and code as the source of truth. |
| Index composition | H12B dual lane: `file_summary`, `file_manifest`, `doc_summary`, `doc_manifest`; no global code-body embeddings. |
| Search/ranking flow | User question -> Gemma 4 26B query planner -> parallel GraphRAG/H12B searches -> deterministic merge -> Gemma 4 26B shared rerank -> bounded documentation/code context -> Gemma 4 26B answer -> optional Gemma 4 26B judge. |
| Model/provider matrix | Local Qwen3-Embedding-0.6B for embeddings; local Gemma 4 26B A4B QAT via llama.cpp for query planning, shared rerank, answer generation, and judge. |
| Dataset | `datasets/protogen_answer_cases_100.jsonl` first; same cases as H12A/H12B. |
| Metrics | Candidate/context Hit@1/3/5/10, recall/precision, citation validity, token/key-token F1, Gemma judge score, latency, total tokens. |
| Cost/latency/index-size | No cloud cost. Expected latency is high because Gemma 26B does planning, shared rerank, answer, and judge. |
| Result summary | Pending. |
| Decision | Promote only if answer judge improves versus H12A while keeping H12B's retrieval gains. |
| Failure modes | Local Gemma may generate weak query plans, shared rerank may overfit to docs, and multi-query planning may add latency without improving context bundle quality. |
| Config | `configs/context-awareness/protogen-h13-gemma26-agentic-doc-graph.yml` |

## Command

```bash
uv run code-diver --config configs/context-awareness/protogen-h13-gemma26-agentic-doc-graph.yml \
  --help-all evaluate-answers \
  --dataset datasets/protogen_answer_cases_100.jsonl \
  --cases 100 \
  --context-files 4 \
  --context-lines 160 \
  --workers 1 \
  --agentic-queries \
  --query-count 4 \
  --query-workers 4 \
  --agentic-query-search-strategy graph_file \
  --agentic-query-rerank \
  --output .code-diver/reports/protogen-h13-gemma26-agentic-doc-graph-100.json \
  --partial-output .code-diver/reports/protogen-h13-gemma26-agentic-doc-graph-100.partial.json \
  --reindex
```

The first run should use `--reindex` because it is a distinct Qdrant collection
with local Gemma generation settings and exact `context_text` storage.

