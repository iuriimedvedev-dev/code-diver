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
| Result summary | Full 100-case local-only run completed. H13 did not beat the earlier H12B locator quality and was much slower: `file_hit=0.8200`, `candidate_file_hit@1=0.6800`, `context_file_hit=0.7900`, mean answer time `242.3s`, four timed-out cases. |
| Decision | Do not promote. Keep as evidence that local Gemma 4 26B agentic query planning/shared rerank is not automatically better than the deterministic H12B-style locator on this repository answer set. |
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

## Completed Result - 2026-06-10

The run used only local models:

- Embeddings: local Qwen3-Embedding-0.6B via the OpenAI-compatible embedding endpoint.
- Query planner: local Gemma 4 26B A4B QAT via llama.cpp.
- Shared reranker: local Gemma 4 26B A4B QAT via llama.cpp.
- Answer model: local Gemma 4 26B A4B QAT via llama.cpp.
- Judge: not run in this row; lexical/citation metrics are from `evaluate-answers`.

Index composition:

```text
file_manifest=20649
file_summary=20649
doc_manifest=1929
doc_summary=1929
total=45156
```

Completed metrics:

| Metric | Value |
| --- | ---: |
| Cases | `100` |
| `file_hit` | `0.8200` |
| `file_recall` | `0.7500` |
| `file_precision` | `0.1240` |
| `file_mrr` | `0.7369` |
| `candidate_file_hit@1` | `0.6800` |
| `candidate_file_hit@3` | `0.7900` |
| `candidate_file_hit@5` | `0.8100` |
| `candidate_file_recall@5` | `0.6850` |
| `context_file_hit` | `0.7900` |
| `context_file_recall` | `0.6550` |
| `context_file_precision` | `0.2700` |
| `planned_query_count` | `3.8400` |
| `planning_duration_ms` | `8218.9291` |
| `rerank_duration_ms` | `28279.1136` |
| `citation_count` | `3.2800` |
| `citation_path_valid_rate` | `0.9400` |
| `citation_line_valid_rate` | `0.9400` |
| `token_f1` | `0.1462` |
| `key_token_f1` | `0.1360` |
| `bigram_f1` | `0.0595` |
| `retrieval_duration_ms` | `207157.0384` |
| `generation_duration_ms` | `27958.7718` |
| `answer_duration_ms_mean` | `242260.5807` |

Timed-out cases:

```text
where-architecture-models
where-command-dispatched
where-feature-flags
where-sample-apps
```

Interpretation:

- H13 did not preserve H12B's strongest retrieval gains. Historical H12B had
  `file_hit=0.8900`, `candidate_file_hit@1=0.7900`, and
  `context_file_hit=0.8900` on the same 100-case answer dataset, although that
  row used Vertex Gemini Lite and older context reconstruction.
- The agentic query planner generated almost four probes per question, but the
  merged/reranked pool still missed or demoted key implementation files.
- The miss pattern is mostly "nearby but wrong subsystem": templates,
  infrastructure, generated examples, and platform auth files displace the
  expected `src/...` implementation files.
- The cost profile is local-only but operationally expensive: mean answer
  latency is about four minutes per case at workers=1, and timeouts are part of
  the observed behavior.

Decision: do not make H13 the default. Keep the agentic branch as a hard-case
fallback candidate only after a faster deterministic/GraphRAG locator has built
a strong candidate pool.
