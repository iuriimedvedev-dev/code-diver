# IntelliJ vLLM Embedding Benchmark - 2026-06-01

Run ID: `7e7e1a3c67ae`

Dataset: `datasets/intellij_eval_1000.jsonl`

Suite: `configs/intellij/intellij-embedding-benchmark.yml`

Index storage: local Qdrant at `http://localhost:6333`

Embedding backend: local vLLM-Metal OpenAI-compatible `/v1/embeddings`

Model: `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`

## Setup Notes

vLLM was installed with UV into `.venv-vllm-metal-official`. Ollama was not used for this run.

The official Hugging Face `Qwen/Qwen3-Embedding-0.6B` checkpoint did not load cleanly through the current vLLM-Metal MLX path because the loader reported unmatched model parameters. The MLX-converted checkpoint loaded and served embeddings successfully.

The working server command shape is:

```bash
VLLM_HOST_IP=127.0.0.1 \
GLOO_SOCKET_IFNAME=lo0 \
VLLM_METAL_MEMORY_FRACTION=0.55 \
.venv-vllm-metal-official/bin/vllm serve mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ \
  --runner pooling \
  --host 127.0.0.1 \
  --port 8001 \
  --max-model-len 512
```

`VLLM_HOST_IP` and `GLOO_SOCKET_IFNAME` are required on this machine to keep Gloo on loopback instead of selecting a non-local interface.

## Index Profile

The IntelliJ profile indexes one compact `file_summary` item per file:

| Setting | Value |
| --- | ---: |
| Indexed items | 74,906 |
| Unique paths | 74,906 |
| Item kinds | `file_summary` only |
| Max input chars | 80 |
| Estimated input tokens | 1,498,120 |
| Embedding cost | $0 |
| Index duration | 227.96s |

This is a fast large-repo baseline, not the best-quality profile. It intentionally avoids line, symbol, structural, and graph expansion to keep the IntelliJ run cheap and reproducible.

## Search Results

Strategy: `hybrid`

Limit: `10`

| Metric | Value |
| --- | ---: |
| Cases | 1,000 |
| Hit@1 | 0.280 |
| Hit@3 | 0.380 |
| Hit@10 | 0.444 |
| MRR@10 | 0.336 |
| nDCG@10 | 0.362 |
| MAP@10 | 0.336 |
| Mean search latency | 40.80ms |
| P95 search latency | 55.48ms |
| LLM calls | 0 |
| LLM cost | $0 |

## Buckets

| Bucket | Cases | Hit@1 | Hit@3 | Hit@10 | MRR@10 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Path/symbol | 375 | 0.216 | 0.317 | 0.365 | 0.269 | 0.292 |
| Semantic | 558 | 0.332 | 0.432 | 0.500 | 0.389 | 0.416 |
| Workflow | 67 | 0.209 | 0.299 | 0.418 | 0.269 | 0.305 |

## Interpretation

The vLLM local embedding path is working and cheap, but this compact file-summary-only profile is not enough for high precision. It is strongest on semantic queries and weakest on exact path/symbol and workflow cases.

The next serious quality experiment should use the same vLLM backend with a richer index profile: file summaries plus capped JVM symbols, AST/structural chunks, graph neighbors, and an LLM rerank stage over the merged candidate set.
