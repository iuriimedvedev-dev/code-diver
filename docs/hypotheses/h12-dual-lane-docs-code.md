# H12 - Dual-Lane Code + Documentation Retrieval

| Field | Value |
| --- | --- |
| ID | `H12` |
| Status | implemented, pending quality eval |
| Motivation | Repository questions often need two different evidence classes: implementation files answer behavior, while README/docs explain terminology, setup, architecture, and project-specific naming. Putting markdown into the same code-metadata lane lets docs either disappear or pollute code ranking. |
| Assumptions | A separate documentation lane can improve LLM reranking and explanation quality without hurting code-file recall, as long as docs have bounded quotas and lower ranking weights. |
| Index composition | Code lane: `file_summary` + `file_manifest`. Documentation lane: `doc_summary` + `doc_manifest` for README/Markdown/RST/ADoc/TXT docs. A compact repository-context artifact can be generated with `llm_readme_summary` and reused by rerank/explanation. Both lanes are currently logical lanes in one vector artifact/collection, not separate physical Qdrant collections. |
| Search/ranking flow | Query -> hybrid retrieval over code lane and docs lane with separate `vector_kind_limits`/weights -> graph-file candidate expansion where configured -> LLM rerank receives `code_candidates` and `documentation_candidates` separately -> answer builder reads documentation context separately from code context. |
| Model/provider matrix | Initial config uses local Qwen3-Embedding-0.6B-compatible embedding endpoint and local Gemma 4 26B-A4B as LLM reranker/explainer. API reranker rows can be added later, but H12 should compare only same model combinations. |
| Dataset | Pending: protogen answer eval and large-repo search/explanation eval. CodeSearchNet is a poor primary benchmark for H12 because its corpus is isolated snippets with little repository documentation. |
| Metrics | Pending. Primary metrics: candidate/context Hit@3/5/10, Recall@5/10, Precision@5/10, answer judge score, citation validity, unsupported-claim rate, latency, token usage, index item counts, and storage size. |
| Cost/latency/index-size | Expected index growth is bounded by two doc items per documentation file. Docs have small quotas by default (`doc_summary`, `doc_manifest`) and should not scale with code body size. |
| Result summary | Implemented as a testable hypothesis. No quality claim yet. |
| Decision | Do not promote until H12 beats same-model H10/H7 controls on explanation quality or retrieval ranking without a significant latency/storage regression. |
| Failure modes | Documentation can be stale, README facts can dominate reranking, docs can hide implementation owners if quotas/weights are too high, and large repos can contain huge vendored docs unless ignores stay strict. |
| Follow-ups | Train/calibrate doc-lane weights; test deterministic README summary vs LLM README summary; add cache invalidation keyed by README/docs hashes; test query-aware docs retrieval; add docs-specific benchmark cases such as setup, architecture, and feature-location questions. |
| Config | `configs/context-awareness/protogen-h12-dual-lane-gemma26.yml` |

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
