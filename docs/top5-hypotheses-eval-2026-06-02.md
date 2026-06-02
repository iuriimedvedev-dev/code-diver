# Top-5 Retrieval Hypotheses Eval, 2026-06-02

Goal: compare the strongest practical search pipelines first on `datasets/protogen_eval_100.jsonl`, then promote the useful ones to the IntelliJ 1000-case eval.

## Hypotheses

| ID | Pipeline | What It Tests | Expected Bottleneck |
|---|---|---|---|
| H1 | Gemini embedding 3072 + hybrid + Gemini Flash-Lite file-first rerank | API quality control: strong embedding plus API LLM reranker | Cost and latency |
| H2 | Qwen3-Embedding-0.6B 4bit + hybrid | Local fast baseline without reranker | Candidate generation and embedding quality |
| H3 | Qwen3-Embedding-0.6B 4bit + Qwen3-Reranker-0.6B top5 | Cheap local cross-encoder rerank | Small reranker capacity |
| H4 | Qwen3-Embedding-0.6B 4bit + Qwen3-Reranker-4B top5 | Stronger local rerank over same candidates | Rerank quality vs latency |
| H5 | Qwen3-Embedding-4B 4bit + Qwen3-Reranker-4B top5 | Stronger local embedding plus stronger local rerank | Index quality vs runtime cost |

## Protogen 100 Results

Dataset shape: `datasets/protogen_eval_100.jsonl` has 100 cases; 62 cases have multiple expected files. Precision and recall are therefore mandatory, not secondary.

| ID | Pipeline | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@10 | Recall@10 | File Precision@R | File Recall@10 | MRR@10 | nDCG@10 | MAP@10 | Mean ms | P95 ms | Cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| H1a | Gemini embedding 3072 + hybrid | 0.60 | 0.83 | 0.87 | 0.92 | 0.492 | 0.910 | 0.535 | 0.795 | 0.719 | 0.689 | 0.613 | 1149 | 2060 | index ~$0.184 |
| H1b | Gemini embedding 3072 + Flash-Lite compact rerank | 0.76 | 0.88 | 0.92 | 0.93 | 0.519 | 0.920 | 0.665 | 0.805 | 0.825 | 0.768 | 0.714 | 1795 | 3048 | +~$0.131 / 100 queries |
| H1c | Gemini embedding 3072 + Flash-Lite file-first rerank | 0.75 | 0.89 | 0.93 | 0.94 | 0.529 | 0.935 | 0.670 | 0.840 | 0.826 | 0.786 | 0.730 | 2715 | 9251 | +~$0.312 / 100 queries |
| H2 | Qwen3-Embedding-0.6B 4bit + hybrid | 0.49 | 0.70 | 0.78 | 0.86 | 0.462 | 0.830 | 0.450 | 0.705 | 0.612 | 0.597 | 0.520 | 589 | 637 | local |
| H3 | Qwen3-Embedding-0.6B 4bit + Qwen3-Reranker-0.6B top5 | 0.59 | 0.76 | 0.78 | 0.85 | 0.460 | 0.825 | 0.545 | 0.695 | 0.678 | 0.640 | 0.579 | 1508 | 4643 | local |
| H4 | Qwen3-Embedding-0.6B 4bit + Qwen3-Reranker-4B top5 | 0.61 | 0.75 | 0.78 | 0.85 | 0.460 | 0.830 | 0.550 | 0.695 | 0.691 | 0.644 | 0.585 | 5645 | 17072 | local |
| H5 | Qwen3-Embedding-4B 4bit + Qwen3-Reranker-4B top5 | 0.62 | 0.81 | 0.84 | 0.87 | 0.398 | 0.845 | 0.555 | 0.695 | 0.712 | 0.647 | 0.580 | 7020 | 22465 | local |

Raw reports:

- `.code-diver/reports/protogen-gemini-api-embedding-3072-api-rerank.json`
- `.code-diver/reports/protogen-top5-h2-qwen06-hybrid.json`
- `.code-diver/reports/protogen-top5-h3-qwen06-rerank06-top5.json`
- `.code-diver/reports/protogen-top5-h4-qwen06-rerank4b-top5.json`
- `.code-diver/reports/protogen-top5-h5-qwen4b-rerank4b-top5.json`

Readout:

- Best quality: H1c by nDCG/MAP/recall and H1b by Hit@1. API rerank is currently the quality leader.
- Best local latency: H2. It is fast but weak on Hit@1 and bundle quality.
- Best local quality: H5 by Hit@1/3/5/10 among local runs, but its mean and p95 latency are not acceptable for interactive search.
- Qwen3-Reranker-4B is not worth using as a blanket reranker on this Mac setup. H4 improves Hit@1 by only +0.02 over H3 while adding ~3.7x mean latency.
- Qwen3-Embedding-4B helps candidate quality at Hit@3/5/10, but does not improve file recall over the 0.6B local stack. That points to index composition and fusion/chunking as bigger levers than just bigger local embeddings.

## IntelliJ Results

Running: `intellij_hybrid_quality` with reindex against `datasets/intellij_eval_1000.jsonl`.

Important dataset caveat: the current IntelliJ 1000-case dataset has 1000 single-answer cases and 0 multi-answer cases. That is useful for a large-scale single-target sanity check, but it is not enough for real workflow questions like "where is user editing handled?" A second IntelliJ dataset slice should add multi-answer workflow cases with expected bundles.

## Notes

- Primary quality metrics: Hit@1, Hit@3, Hit@5, MRR@10, nDCG@10.
- Mandatory multi-answer metrics: Precision@10, Recall@10, File Precision@R, File Recall@10, MAP@10.
- Primary runtime metrics: mean latency, p95 latency, index time, model startup time, API token/cost usage.
- A reranker can only improve Hit@1 if the expected file is inside the candidate set. Hit@3/Hit@5 are tracked to separate candidate generation failures from ranking failures.
