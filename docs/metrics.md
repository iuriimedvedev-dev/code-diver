# Retrieval Metrics

This project measures retrieval quality before answer generation. The goal is to know whether the search layer returns the right files or symbols inside a small top-k context budget.

## Dataset Case Shape

Each JSONL case has:

- `id`: stable case id.
- `query`: natural-language retrieval query.
- `expected`: list of expected item ids or path prefixes.

An item is counted as relevant when its indexed id matches an expected id exactly, or when its path starts with an expected path prefix.

## Metrics

| Metric | Meaning | Good value | What it tells us |
| --- | --- | ---: | --- |
| `cases` | Number of evaluation cases included in the run. | Higher is better for confidence. | Small values make results noisy. Current protogen eval has 10 cases, so treat differences below ~0.1 carefully. |
| `hit_rate@10` | Fraction of cases where at least one relevant item appears in the top 10. | `1.0` | Measures whether a user or agent would see any useful result in the first page. This is the main quality guardrail. |
| `mrr@10` | Mean reciprocal rank of the first relevant item in top 10. Rank 1 = `1.0`, rank 2 = `0.5`, rank 10 = `0.1`, no hit = `0`. | `1.0` | Measures ranking quality. High hit rate with low MRR means relevant files are present but buried. |
| `precision@10` | Relevant retrieved items divided by retrieved items, averaged across cases. | `1.0` | Measures result cleanliness. Low precision means the model will waste context tokens on irrelevant snippets. |
| `recall@10` | Expected relevant targets found in top 10, averaged across cases. | `1.0` | Measures coverage when a case has multiple expected files. |
| `duration_ms` | Wall-clock evaluation time for that strategy over all cases. | Lower is better. | Measures retrieval latency in the current implementation and storage backend. Do not compare across machines without noting hardware/backend. |

## How To Read The Metrics

Use `hit_rate@10` first. If it is low, the strategy misses the target files and is not production-ready.

Use `mrr@10` second. If hit rate is acceptable but MRR is low, reranking or path/symbol boosting should be the next step.

Use `precision@10` to estimate token waste. A strategy with high hit rate and low precision can answer simple questions but will inflate context and cost.

Use `duration_ms` only together with backend details. JSON vector search is brute-force and slow for dense embeddings. Qdrant should be used for serious local/API embedding speed comparisons.

## Current `../protogen` Runs

Dataset: `datasets/protogen_eval.jsonl`, 10 repository-location cases, `limit=10`.

| Config | Embeddings | Indexing | Strategy | Items | Hit@10 | MRR@10 | Precision@10 | Recall@10 | Duration |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `configs/protogen-baseline.yml` | hash-token-v1 | line chunks | vector | 2444 | 0.70 | 0.372 | n/a | n/a | n/a |
| `configs/protogen-symbols.yml` | hash-token-v1 | line+symbol+AST graph | vector | 8842 | 0.30 | 0.250 | 0.100 | 0.300 | 4.8s |
| `configs/protogen-symbols.yml` | hash-token-v1 | line+symbol+AST graph | recursive | 8842 | 0.50 | 0.298 | 0.070 | 0.500 | 19.1s |
| `configs/protogen-symbols.yml` | hash-token-v1 | line+symbol+AST graph | graph | 8842 | 0.30 | 0.220 | 0.100 | 0.300 | 7.6s |
| `configs/protogen-ollama-embeddings.yml` | local `mxbai-embed-large` | line+symbol+AST graph | vector | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 14.4s |
| `configs/protogen-ollama-embeddings.yml` | local `mxbai-embed-large` | line+symbol+AST graph | recursive | 8246 | 0.90 | 0.612 | 0.310 | 0.850 | 57.9s |
| `configs/protogen-ollama-embeddings.yml` | local `mxbai-embed-large` | line+symbol+AST graph | graph | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 17.1s |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | line+symbol+AST graph | vector | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 0.4s |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | line+symbol+AST graph | recursive | 8246 | 0.90 | 0.612 | 0.310 | 0.850 | 1.4s |
| `configs/protogen-ollama-qdrant.yml` | local `mxbai-embed-large` + embedded Qdrant | line+symbol+AST graph | graph | 8246 | 0.90 | 0.663 | 0.310 | 0.900 | 3.8s |
| `configs/protogen-vertex-smoke.yml` | Vertex `gemini-embedding-2` | selected-file smoke index | vector | 603 | 0.70 | 0.700 | 0.470 | 0.700 | 6.5s |
| `configs/protogen-vertex-smoke.yml` | Vertex `gemini-embedding-2` | selected-file smoke index | recursive | 603 | 0.70 | 0.700 | 0.492 | 0.700 | 30.7s |
| `configs/protogen-vertex-smoke.yml` | Vertex `gemini-embedding-2` | selected-file smoke index | graph | 603 | 0.70 | 0.700 | 0.470 | 0.700 | 6.3s |

`n/a` means the older run was recorded before full metric output was documented.

## Local Vs API Read

Based on current measured retrieval metrics, the local Ollama embedding model is better than the hash baseline by a large margin on `../protogen`: `hit@10` improves to `0.90`, and `mrr@10` improves to `0.663`.

This does not yet prove local embeddings are better than Gemini/Vertex embeddings. Vertex now works through refreshed ADC, but the recorded Vertex run is a selected-file smoke index, not a full-repository benchmark. Full Vertex indexing is possible, but `gemini-embedding-2` on Vertex currently behaves as one-content-per-request in our SDK path, so a full 8k-item run needs explicit cost/time budgeting or more aggressive parallelism.

Practical conclusion right now:

- Use local `mxbai-embed-large` for fast iteration, privacy, and no per-token embedding cost.
- Use Qdrant for local embeddings; embedded Qdrant reduced vector evaluation from `14.4s` to `0.4s` on the same dataset.
- Use Gemini/Vertex embeddings when we need a stronger semantic model and can pay API latency/cost.
- Keep hash embeddings only as a reproducible control baseline, not as a quality target.

## Known Measurement Limits

- Current dataset has only 10 cases.
- Metrics evaluate retrieval, not final answer correctness.
- `duration_ms` includes Python implementation overhead and JSON vector store scans.
- Recursive search currently increases latency significantly and does not always improve quality over strong embeddings.
- Graph retrieval currently expands useful AST/import neighbors, but still needs path/symbol boosts and reranking to beat vector search consistently.
