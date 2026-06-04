# Code Embedding Model Research - 2026-06-04

## Decision

Add `google/embeddinggemma-300m` as a first-class local embedding profile, but keep Qwen3
Embedding 0.6B as the practical default until our own benchmark proves otherwise.
EmbeddingGemma is attractive because it is tiny, on-device oriented, supports MRL-style
768/512/256/128-dimensional usage, and has explicit code-retrieval prompting. It is not
clearly the best code retriever overall.

## Current Candidates

| Candidate | Local/API | Why test it | Main risk |
| --- | --- | --- | --- |
| `Qwen/Qwen3-Embedding-0.6B` | local | Strong small open model; already integrated and fast enough for candidate generation. | Can rank correct files too low without hybrid signals/rerank. |
| `Qwen/Qwen3-Embedding-4B` | local | Meaningfully stronger retrieval benchmark scores than 0.6B. | Slower and heavier for always-hot local usage. |
| `google/embeddinggemma-300m` | local | Very small Gemma-family embedding model with code prompt support and cheap memory footprint. | Gated license; 2K context; likely weaker than larger Qwen/Gemini/Voyage on hard code retrieval. |
| `gemini-embedding-2` | API/Vertex | Strongest Google API candidate; reported very strong MTEB Code performance. | Cost/latency and quota; not local. |
| `voyage-code-3` | API | Purpose-built code embedding model with strong vendor-reported code retrieval results and compact vectors. | API dependency; provider not implemented yet. |
| `jina-code-embeddings-0.5b/1.5b` | local/API depending runtime | Code-specialized open models reported strong on MTEB-Code/CoIR-style tasks. | Need provider/runtime validation; not yet integrated. |
| `Codestral Embed` | API | Code-specific commercial candidate worth watching. | API dependency; no local path in this project yet. |

## Implementation Notes

New profiles:

- `embeddinggemma-300m`: Apple Silicon/vLLM-Metal profile.
- `embeddinggemma-300m-vllm`: Nvidia CUDA, AMD ROCm, or CPU vLLM profile.

Both profiles use:

- model: `google/embeddinggemma-300m`;
- dimensions: `768`;
- document prefix: `title: none | text: `;
- query prefix: `task: code retrieval | query: `;
- max input chars: `1200`, keeping inputs comfortably below the 2K token context.

First-start requirement: accept the Gemma license on Hugging Face and export `HF_TOKEN` so
vLLM can download the gated weights.

## Next Eval Matrix

Run the same H5/Pure-H3 file-locator pipeline against:

1. Qwen3 0.6B local.
2. Qwen3 4B local.
3. EmbeddingGemma 300M local.
4. Gemini Embedding 2 API, only on a capped slice if spend is a concern.

Primary metrics: Hit@1, Hit@3, Hit@5, Hit@10, Recall@5, Precision@5, MRR, nDCG@10,
index wall time, query latency, index size, and tokens/cost for any LLM-reranked path.
