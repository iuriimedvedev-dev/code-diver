# llama.cpp Rerank Runtime Notes - 2026-06-02

## What Went Wrong

The slow local Qwen3 rerank experiment was not only a model/runtime issue.
Two local bugs made us benchmark the wrong thing:

- `CrossEncoderRerankRetrievalStrategy` used `max(limit, candidate_limit)` and sent all returned candidates to the reranker. With `evaluation.limit: 10`, a `candidate_limit: 5` hypothesis still reranked 10 documents.
- `ExperimentRunner` applied `generation`, `hybrid_search`, and `llm_rerank` hypothesis overrides, but ignored `cross_encoder_rerank`. CLI `experiment` therefore used the base cross-encoder config instead of the hypothesis-specific one.

Both are fixed and covered by unit tests.

## llama.cpp Findings

The known-good command on this MacBook M3 Max is:

```bash
llama-server \
  --model .code-diver/models/rerankers/qwen3-reranker-4b/Qwen3-Reranker-4B-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  --embedding \
  --reranking \
  --pooling rank
```

It starts with `n_parallel = 4` and `n_ctx = 40960` per slot on this build.

The attempted tuned profiles were not reliable:

- `--ctx-size 8192 --parallel 4` starts and reports 4 slots with `n_ctx = 2048`, but HTTP was not reachable in the observed run.
- Adding `--threads`, `--threads-batch`, `--batch-size`, `--metrics`, `--no-ui`, `--no-cache-prompt`, or `--flash-attn on` made the server fail to become reachable before bind/listen or hang after startup.
- `--batch-size` above `--ubatch-size` is forced down to `512` in this reranking/embedding server mode, so it did not improve throughput in our run.

Upstream llama.cpp documents the important interaction: `llama-server -c 16384 -np 4` means 4 concurrent requests with 4096 context each. So `ctx-size` is total server context divided across slots in common server examples, and tuning `--parallel` without validating effective slot context can accidentally make every request too small.

The official server README also says `/reranking`, `/rerank`, `/v1/rerank`, and `/v1/reranking` are aliases, and that reranking requires a reranker model plus `--embedding --pooling rank`. So our baseline command should include all three mode flags: `--embedding`, `--reranking`, and `--pooling rank`.

## Practical Runtime Decision

For now, do not spend quality-eval time on aggressive llama.cpp server tuning.

Use:

- baseline `llama-server --embedding --reranking --pooling rank`;
- `evaluation.workers: 4`;
- cross-encoder `candidate_limit: 3` or `5` for interactive/cascade experiments;
- `candidate_limit: 10` only for batch-quality runs;
- avoid `candidate_limit: 40` locally unless the goal is an offline overnight batch.

## Next Runtime Experiments

Run these as isolated microbenchmarks before using them in full eval:

1. Baseline server, top-3/top-5/top-10 rerank latency.
2. `--ctx-size 16384 --parallel 4` with a direct `/v1/rerank` smoke and 20 repeated requests.
3. `--ctx-size 32768 --parallel 4` with the same smoke.
4. If those work, test one flag at a time: `--flash-attn auto`, then `--threads`, then `--metrics`.
5. If Qwen3-Reranker-4B remains too slow, evaluate Qwen3-Reranker-0.6B for interactive rerank and keep 4B for offline quality mode.

## Sources Checked

- ggml-org/llama.cpp server README: rerank endpoints, required reranker flags, continuous batching and parallel decoding.
- ggml-org/llama.cpp root README: Apple Silicon/Metal support, quantization support, and `llama-server -c 16384 -np 4` concurrency example.
- ggml-org/llama.cpp discussions/issues around `--ctx-size` and `--parallel`: slot context can be surprising, so validate server startup logs and direct `/v1/rerank` smoke before running full evals.
