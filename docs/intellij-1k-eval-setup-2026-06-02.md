# IntelliJ 1k Eval Setup - 2026-06-02

## Status

The IntelliJ 1k evaluation dataset is prepared and reproducible.

| Artifact | Status |
| --- | --- |
| Dataset | `datasets/intellij_eval_1000.jsonl` |
| Generator | `scripts/generate_intellij_eval.py` |
| Source repo | `../intellij-community` |
| Case count | 1,000 |
| Baseline config | `configs/intellij-community-vllm-qdrant.yml` |
| Quality config | `configs/intellij-community-hybrid-quality.yml` |

Reproducibility check:

```bash
uv run python scripts/generate_intellij_eval.py \
  --root ../intellij-community \
  --output /private/tmp/intellij_eval_check.jsonl \
  --limit 1000
```

The generated `/private/tmp/intellij_eval_check.jsonl` matches the checked-in dataset byte-for-byte.

## Dataset Shape

The generator mixes four case families:

| Family | Purpose |
| --- | --- |
| Intent cases | Hand-written IDE workflow questions, such as project opening, indexing, VFS refresh, inspections, completion, and plugin loading. |
| Source symbol cases | Automatically generated class/method questions from Java/Kotlin symbols. |
| Config cases | Plugin descriptors, Gradle files, YAML, JSON, properties, and XML configuration. |
| Path intent cases | File/path-derived behavior questions. |

This is still an imperfect dataset because many cases are generated from symbols and paths. It is useful for large-repo stress testing, but it should be extended with more hand-written informal workflow cases before we treat it as a final quality benchmark.

## Existing Baseline

`docs/intellij-vllm-embedding-benchmark-2026-06-01.md` measured the fast local baseline:

| Setting | Value |
| --- | --- |
| Index profile | file-summary-only |
| Items | 74,906 |
| Embedding backend | vLLM-Metal, Qwen3 Embedding 0.6B 4-bit |
| Dataset | `datasets/intellij_eval_1000.jsonl` |

| Metric | Value |
| --- | ---: |
| Hit@1 | 0.280 |
| Hit@3 | 0.380 |
| Hit@10 | 0.444 |
| MRR@10 | 0.336 |
| nDCG@10 | 0.362 |
| Mean latency | 40.80ms/query |

Interpretation: this baseline proves the local large-repo path works, but it is intentionally under-indexed. It should not be used as the quality ceiling.

## Quality Config

`configs/intellij-community-hybrid-quality.yml` is the prepared quality profile for the next heavy run.

It enables:

| Component | Setting |
| --- | --- |
| File summaries | enabled |
| Symbol chunks | enabled, capped at 32 symbols per file |
| Structural chunks | enabled |
| Line chunks | disabled for now to control index size |
| Graph | enabled, AST/reference/call edges |
| Hybrid retrieval | vector + BM25 + path + symbol + graph + file vote |
| Cross-encoder rerank | llama.cpp `/v1/rerank`, `Qwen3-Reranker-0.6B` |
| LLM rerank hypothesis | Vertex/Gemini Flash-Lite file-first rerank |

Planned command shape:

```bash
uv run code-diver --config configs/intellij-community-hybrid-quality.yml index
uv run code-diver --config configs/intellij-community-hybrid-quality.yml experiment \
  --hypothesis intellij_hybrid_quality \
  --hypothesis intellij_hybrid_quality_cross_encoder \
  --json
```

The quality run is expected to be much slower and larger than the file-summary-only baseline. It should be run after confirming local Qdrant, vLLM embeddings, and llama.cpp rerank are healthy.

## Current Gap

The prepared dataset and config are ready, but the full quality index/eval has not completed yet in this slice. The next measurable target is to beat the baseline `Hit@1=0.280` and `Hit@10=0.444` on the same 1,000 cases with the richer index.
