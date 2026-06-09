# H12 - Dual-Lane Code + Documentation Retrieval

| Field | Value |
| --- | --- |
| ID | `H12` |
| Status | implemented, active A/B eval |
| Motivation | Repository questions often need two different evidence classes: implementation files answer behavior, while README/docs explain terminology, setup, architecture, and project-specific naming. Putting markdown into the same code-metadata lane lets docs either disappear or pollute code ranking. |
| Assumptions | A separate documentation lane can improve LLM reranking and explanation quality without hurting code-file recall, as long as docs have bounded quotas and lower ranking weights. |
| Index composition | Code lane: `file_summary` + `file_manifest`. Documentation lane: `doc_summary` + `doc_manifest` for README/Markdown/RST/ADoc/TXT docs. A compact repository-context artifact can be generated with `llm_readme_summary` and reused by rerank/explanation. Both lanes are currently logical lanes in one vector artifact/collection, not separate physical Qdrant collections. |
| Search/ranking flow | Query -> hybrid retrieval over code lane and docs lane with separate `vector_kind_limits`/weights -> graph-file candidate expansion where configured -> LLM rerank receives `code_candidates` and `documentation_candidates` separately -> answer builder reads documentation context separately from code context. |
| Model/provider matrix | Initial config uses local Qwen3-Embedding-0.6B-compatible embedding endpoint and local Gemma 4 26B-A4B as LLM reranker/explainer. API reranker rows can be added later, but H12 should compare only same model combinations. |
| Dataset | Primary: `datasets/protogen_answer_cases_100.jsonl`. CodeSearchNet is a poor primary benchmark for H12 because its corpus is isolated snippets with little repository documentation. |
| Metrics | Primary metrics: candidate/context Hit@1/3/5/10, Recall@5/10, Precision@5/10, answer judge score, citation validity, token/key-token F1, latency, token usage, index item counts, and storage size. |
| Cost/latency/index-size | Expected index growth is bounded by two doc items per documentation file. Docs have small quotas by default (`doc_summary`, `doc_manifest`) and should not scale with code body size. |
| Result summary | H12A context-artifact control completed on 100 protogen answer cases. H12B doc-vector lane is the matching active run. Do not claim a winner until both reports are complete and judged with the same judge model/prompt. |
| Decision | Do not promote until H12 beats same-model controls on explanation quality or retrieval ranking without a significant latency/storage regression. Because H10 GraphRAG only showed a marginal same-reranker lift on CodeSearchNet, H12 must be measured in both variants: no-graph and graph. |
| Failure modes | Documentation can be stale, README facts can dominate reranking, docs can hide implementation owners if quotas/weights are too high, and large repos can contain huge vendored docs unless ignores stay strict. |
| Follow-ups | Train/calibrate doc-lane weights; test deterministic README summary vs LLM README summary; add cache invalidation keyed by README/docs hashes; test query-aware docs retrieval; add docs-specific benchmark cases such as setup, architecture, and feature-location questions. |
| Configs | `configs/context-awareness/protogen-h12a-context-artifact-vertex.yml`, `configs/context-awareness/protogen-h12b-doc-vector-lane-vertex.yml`, `configs/context-awareness/protogen-h12-dual-lane-gemma26.yml` |

## Implementation Notes

H12 intentionally keeps the physical storage simple for now:

```text
same Qdrant collection / JSON artifact
  code lane: file_summary, file_manifest
  docs lane: doc_summary, doc_manifest
```

This still gives us two retrieval lanes because the search config can allocate
separate quotas, multipliers, and item-kind weights to each `index_kind`. The
advantage is that indexing, update, pruning, graph artifacts, and evaluation do
not need a second store lifecycle yet.

The LLM prompt receives grouped candidates:

```json
{
  "candidate_groups": {
    "code_candidates": [],
    "documentation_candidates": []
  }
}
```

The answer context builder also separates evidence:

```text
Documentation context
Code context
```

Documentation does not consume the configured code-file context budget, so a
README hit cannot push the implementation file out of the explanation prompt.

For H12, `pi.repo_context.mode: llm_readme_summary` asks the configured
generation provider to build a compact README summary once and stores it at the
configured `.code-diver/context/repository-context.md` path. If no summarizer is
provided by the command path, the context builder falls back to the deterministic
fact-preserving summary and marks that fallback in the artifact.

## Required A/B Shape

H12 changes the documentation/context axis. It must not be used to also smuggle
in a graph change unless the matching control exists.

| Row | Candidate generator | Docs lane | Repo context | Reranker | Purpose |
| --- | --- | --- | --- | --- | --- |
| H12A context-artifact | graph-file rerank | off | compact README/docs | Vertex Gemini Lite | Does compact repository context help without vector-indexing docs? |
| H12B doc-vector lane | graph-file rerank | on | compact README/docs | Vertex Gemini Lite | Does giving non-code files their own vector lane improve retrieval/answers? |
| H12-no-graph | calibrated hybrid | on | compact README/docs | same model | Isolate docs/context impact without graph propagation. |
| H12-graph | graph-file rerank | on | compact README/docs | same model | Measure whether docs/context composes with GraphRAG. |

Compare these against matching non-H12 rows:

| Control | Candidate generator | Docs lane | Repo context | Reranker |
| --- | --- | --- | --- | --- |
| H6/H7 control | calibrated hybrid | off | off | same model |
| H10 control | graph-file rerank | off | off | same model |

## Active A/B: Non-Code Indexing

We are currently comparing two ways to use non-code files while keeping the rest
of the pipeline fixed:

```text
same repo: protogen
same dataset: datasets/protogen_answer_cases_100.jsonl
same embeddings: Qwen3-Embedding-0.6B, local OpenAI-compatible endpoint
same reranker/answerer: Vertex Gemini 3.1 Flash Lite
same graph mode: graph_file_rerank with references
same context width: 4 code files x 160 lines
```

### H12A: Context Artifact Only

Command:

```bash
uv run code-diver --config configs/context-awareness/protogen-h12a-context-artifact-vertex.yml \
  evaluate-answers \
  --dataset datasets/protogen_answer_cases_100.jsonl \
  --cases 100 \
  --context-files 4 \
  --context-lines 160 \
  --workers 2 \
  --output .code-diver/reports/protogen-h12a-context-artifact-vertex-100.json \
  --partial-output .code-diver/reports/protogen-h12a-context-artifact-vertex-100.partial.json \
  --reindex
```

Completed result:

| Metric | Value |
| --- | ---: |
| `file_hit` | `0.8600` |
| `file_recall` | `0.7700` |
| `file_precision` | `0.1230` |
| `file_mrr` | `0.7608` |
| `candidate_file_hit@1` | `0.6800` |
| `candidate_file_hit@3` | `0.8500` |
| `candidate_file_hit@5` | `0.8600` |
| `context_file_hit` | `0.8600` |
| `context_file_recall` | `0.7150` |
| `token_f1` | `0.1791` |
| `key_token_f1` | `0.1697` |
| `citation_path_valid_rate` | `0.9567` |
| `retrieval_duration_ms` | `27574.4394` |
| `generation_duration_ms` | `3199.5262` |

Index composition:

```text
file_manifest=22578
file_summary=22578
doc_manifest=0
doc_summary=0
```

### H12B: Documentation Vector Lane

Command:

```bash
uv run code-diver --config configs/context-awareness/protogen-h12b-doc-vector-lane-vertex.yml \
  evaluate-answers \
  --dataset datasets/protogen_answer_cases_100.jsonl \
  --cases 100 \
  --context-files 4 \
  --context-lines 160 \
  --workers 2 \
  --output .code-diver/reports/protogen-h12b-doc-vector-lane-vertex-100.json \
  --partial-output .code-diver/reports/protogen-h12b-doc-vector-lane-vertex-100.partial.json \
  --reindex
```

Index composition observed during the run:

```text
file_manifest=20649
file_summary=20649
doc_manifest=1929
doc_summary=1929
```

This keeps total vector count equal to H12A (`45156`) while reallocating part of
the vector budget from code-file metadata to non-code documentation metadata.
That makes the comparison cleaner: if H12B wins, it is because the docs lane
adds useful signal, not because it simply indexed more total points.

## Post-Hoc Report and Judge

Use `answer-report` to compare saved reports without rerunning retrieval:

```bash
uv run code-diver --help-all answer-report \
  .code-diver/reports/protogen-h12a-context-artifact-vertex-100.json \
  .code-diver/reports/protogen-h12b-doc-vector-lane-vertex-100.json
```

Use the same command to run the answer judge later over a saved report:

```bash
uv run code-diver --config configs/context-awareness/protogen-h12b-doc-vector-lane-vertex.yml \
  --help-all answer-report \
  .code-diver/reports/protogen-h12b-doc-vector-lane-vertex-100.json \
  --judge \
  --judge-prompt prompts/code-answer-judge.md \
  --output .code-diver/reports/protogen-h12b-doc-vector-lane-vertex-100.judged.json
```

New `evaluate-answers` runs store `context_text` by default so post-hoc judging
has the same evidence the answer model saw. Older reports can still be judged by
reconstructing bounded context from saved `retrieved_files` and `settings.root`,
but those judged results should be marked as reconstructed-context runs.
