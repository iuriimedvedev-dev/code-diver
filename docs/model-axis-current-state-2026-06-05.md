# Model Axis Current State - 2026-06-05

## Product Pipeline

The product is not just file retrieval. The intended runtime is:

```text
user question
-> H6.1 locator finds candidate files
-> reranker chooses the best candidate file set/order
-> orchestrator/explainer reads outlines, symbols, grep/rg hits, and source ranges
-> final answer explains the code with evidence
```

Older notes use `static` to mean "deterministic locator only." That is only the
candidate-generation stage, not the whole product.

## Three Separate Model Variables

| Variable | Job | Current best evidence | Current decision |
| --- | --- | --- | --- |
| Embedding model | Build/query the H6.1 file metadata locator. | EmbeddingGemma-300M H6.1 is the current best same-stack local default. Earlier Qwen3 0.6B/4B tests were weaker after rerank on Protogen; Qwen 4B improved raw candidate generation but did not improve the best Gemini-reranked result. | Keep EmbeddingGemma-300M as default, continue controlled A/B against Qwen 0.6B/4B and code-specialized embeddings. |
| Reranker model | Reorder a fixed candidate set from H6.1. | Gemini 3.1 Flash Lite is historically strong and cheap. Gemma E2B failed when tested as combined agent+reranker; that does not fully isolate rerank-only quality. | Need one-shot rerank-only matrix. Do not judge local rerank only from open-ended agent loop. |
| Orchestrator/explainer model | Use tools, read code, and answer the user. | Gemma E4B is the best local explainer so far on CodeXGLUE-style explanation eval. Gemma E2B produced too many malformed structured explanations. Qwen3.5 9B is useful as a cross-family judge. | Use H6.1 candidates, then test explainer quality separately from retrieval Hit@K. |

## Same-Index Agent/Rerank Result

This was the latest 100-case CodeSearchNet run over the same H6.1 EmbeddingGemma
candidate generator:

| Setup | Cases | Hit@1 | Hit@5 | Hit@10 | Precision@10 | nDCG@10 | Mean ms | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| H6.1 deterministic locator | 100 | 0.820 | 0.970 | 0.970 | 0.147 | 0.900 | 858 | Best broad candidate generation. |
| H6.1 + Gemini 3.1 Flash Lite agent/rerank | 100 | 0.740 | 0.860 | 0.860 | 0.277 | 0.813 | 10,660 | Better precision, worse recall. Candidate for gated precision mode. |
| H6.1 + Gemma 4 E2B local agent/rerank | 100 | 0.510 | 0.640 | 0.700 | 0.070 | 0.596 | 11,501 | Fully local and stable, but not good enough for search ranking. |

Interpretation:

- H6.1 locator is currently the best broad candidate generator.
- Gemini Lite can narrow results and improve Precision@10, but as an unrestricted
  agent loop it drops too many correct files.
- Gemma E2B should not rerank search results in the current prompt/tool contract.

## What We Still Need To Test

### 1. Embedding Axis

Run identical H6.1 locator configs with:

- `google/embeddinggemma-300m`
- Qwen3-Embedding 0.6B
- Qwen3-Embedding 4B
- any current code-specific local embedding candidate that fits the runtime

Metrics:

- index build time;
- index size;
- Hit@1/3/5/10;
- Recall@10;
- Precision@10;
- MRR/nDCG;
- mean/p95 query latency.

### 2. Reranker Axis

Do **not** give the model full search control for this test. Freeze H6.1 top-N
candidates and run one-shot rerank:

```text
query + structured top-N candidates -> reranked file list
```

Candidates:

- Gemini 3.1 Flash Lite;
- Gemma 4 E2B;
- Gemma 4 E4B;
- Qwen3.5 local;
- Qwen3-Reranker cross-encoder if a real rerank endpoint is available.

This isolates whether a local model can rank files. The latest E2B agent result
does not isolate that because it mixes query planning, tool selection, and rerank.

### 3. Orchestrator / Explainer Axis

This is a separate product metric:

```text
question + H6.1 candidates -> tool reads -> final explanation answer
```

Retrieval Hit@K cannot score this. We need:

- answer groundedness;
- cited file/line correctness;
- completeness;
- clarity;
- whether the answer read the right files;
- AI-judge rubric with cross-family judge control.

Current local explainer evidence points to Gemma E4B over Gemma E2B. Qwen3.5 9B
is useful as cross-family judge, not yet proven as the best explainer.
