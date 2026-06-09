# H14 - Text Graph Context

## Question

Can documentation become a useful graph signal instead of only a vector/BM25/context lane?

## Baseline

H13 combines:

- H12B dual-lane index: file summaries, file manifests, doc summaries, doc manifests.
- Code GraphRAG over file-level graph candidates.
- Calibrated H6.1 hybrid weights.
- Local Gemma 4 26B for query planning, shared reranking, answering, and judging.

## Change

H14 keeps the H13 model stack and calibrated hybrid weights, then adds a deterministic documentation graph:

- `doc_chunk` nodes are indexed only for documentation files.
- `doc_summary` and `doc_manifest` summarize `doc_chunk` nodes from the same file.
- Adjacent documentation chunks keep same-file neighborhood continuity.
- Markdown links and backticked repository paths create `references` edges from docs to code or other docs.
- `doc_summary`, `doc_manifest`, and `doc_chunk` are first-class representatives in the file graph catalog.

This is intentionally not LLM-generated graph extraction. The variable under test is the text graph, not a second model-driven indexing pass.

## Controlled Variables

- Embeddings: local `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`.
- Reranker/answerer/judge: local `gemma-4-26B-A4B-it-qat-UD-Q4_K_XL`.
- Search strategy: `graph_file_rerank`.
- Hybrid weights: `vector=0.42`, `lexical=0.26`, `path=0.12`, `symbol=0.10`, `symbol_match=0.10`, `file_vote=0.06`.
- Graph file weights: `vector=0.25`, `lexical=0.25`, `path=0.20`, `symbol=0.10`, `graph=0.45`.

## Command

```bash
uv run code-diver --config configs/context-awareness/protogen-h14-gemma26-text-graph.yml \
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
  --output .code-diver/reports/protogen-h14-gemma26-text-graph-100.json \
  --partial-output .code-diver/reports/protogen-h14-gemma26-text-graph-100.partial.json \
  --reindex
```

Then judge with the same local model:

```bash
uv run code-diver --config configs/context-awareness/protogen-h14-gemma26-text-graph.yml \
  --help-all answer-report \
  .code-diver/reports/protogen-h14-gemma26-text-graph-100.json \
  --judge \
  --judge-prompt prompts/code-answer-judge.md \
  --workers 1 \
  --context-files 4 \
  --context-lines 160 \
  --output .code-diver/reports/protogen-h14-gemma26-text-graph-100.gemma26-judge.json
```

## Metrics

Primary:

- `file_hit`, `file_recall`, `file_precision`, `file_mrr`.
- `candidate_file_hit@1/@3/@5`.
- `context_file_hit`, `context_file_recall`.
- Gemma judge overall score and rubric dimensions.

Secondary:

- `token_f1`, `key_token_f1`.
- citation path and line validity.
- retrieval/generation/judge latency.
- index item counts and graph edge counts.

## Expected Outcome

The text graph should help repository-level and setup/architecture questions where documentation points to implementation files. It may hurt implementation-only questions if documentation candidates crowd out code files. That is why H14 keeps doc chunk caps conservative and reports code/doc hits separately where possible.
