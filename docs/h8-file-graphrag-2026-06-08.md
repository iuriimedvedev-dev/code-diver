# H8 File GraphRAG - 2026-06-08

## Purpose

Test the direct file-level GraphRAG idea:

```text
use graph for finding files
use the existing best file/content inspection path after that
```

This is not item/chunk GraphRAG. The implementation projects item-level graph
edges into file->file edges and assigns graph scores back to file-level
representatives (`file_summary`, `file_manifest`, `file_api_manifest`).

## Implementation

Added:

- `FileGraphCandidateExpander`;
- `hybrid_search.graph_scope`;
- config value `graph_scope: file`;
- H8 benchmark config:
  `configs/benchmarks/codesearchnet-h8-file-graphrag-embeddinggemma-1000.yml`.

Default remains `graph_scope: item`, so existing H7 behavior is unchanged.

## Run

Command:

```bash
uv run code-diver \
  --config configs/benchmarks/codesearchnet-h8-file-graphrag-embeddinggemma-1000.yml \
  evaluate \
  --reindex \
  --details
```

Dataset:

- CodeSearchNet/MTEB Python local positive slice;
- 1,000 cases;
- local EmbeddingGemma-300M;
- no LLM/API rerank.

## Result

| Setup | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Recall@10 | Precision@10 | nDCG@10 | MAP@10 | Mean ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H7 local file locator | 0.857 | 0.957 | 0.980 | 0.987 | 0.987 | 0.1519 | 0.9284 | 0.9088 | 792 | 867 |
| H8 file GraphRAG | 0.855 | 0.958 | 0.980 | 0.986 | 0.986 | 0.1425 | 0.9271 | 0.9073 | 796 | 881 |

## Decision

Do not promote H8 file GraphRAG as the default.

It slightly improves Hit@3 (`+0.001`) but slightly hurts Hit@1, Hit@10,
precision, nDCG, MAP, and p95 latency. On this CodeSearchNet slice, the graph is
not informative enough to beat the calibrated H7 file locator.

## Interpretation

The idea is still technically sound for real repositories. The likely problem
is the benchmark structure:

- CodeSearchNet materialized snippets have weak real module/file topology;
- reference edges mostly capture shared terms;
- shared-term file neighbors can be semantically plausible but not the exact
  labeled file;
- single-positive labels punish useful neighboring files that are not the
  expected file.

The next useful GraphRAG test should use real repository graphs with typed
edges:

- imports;
- routes;
- dependency injection;
- service registration;
- config-declares;
- tests-for;
- generated-from.

Use graph expansion only after H7 seeds and preferably only for workflow or
low-confidence routes.
