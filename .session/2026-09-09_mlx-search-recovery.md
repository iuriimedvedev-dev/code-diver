# MLX search recovery — 2026-09-09

## Outcome

The pinned `vllm-metal` Qwen3 reranker was launched only on owned port
`18083` with explicit conservative settings: `VLLM_METAL_MEMORY_FRACTION=0.35`,
`--gpu-memory-utilization 0.35`, paged attention, `--max-num-seqs 1`, block
size `16`, and `2048`-token batch/scheduled ceilings. Official-template
semantic smoke passed: two-document cold/warm `0.464/0.068 s`, fixed 34-short
`0.392 s`, and fixed 34-long `1.307 s`; Beijing ranked first in every result.

Memory free fell from `49%` before the MLX smoke to `20%` after the 34-short
request and recovered to `56%` after stopping the owned server. The service was
stopped promptly; embedding `8001`, llama `18081`, and Qdrant `6333` remained
HTTP 200 and were never restarted or stopped.

## Blocker

The existing evaluator tests passed `4/4`. A truthful in-memory route override
can set Python CE, Rust CE, embedding, and Qdrant to `127.0.0.1` while retaining
retrieval/candidate/result budgets `360/34/10`, but
`local_embedding_profile_key` still returns `qwen3-0.6b` for the exact IPv4
embedding tuple. `research_rust_full_eval.py` then intentionally raises before
provider construction to prevent runtime management. No guard bypass,
application edit, or silent `localhost` fallback was used.

Consequently the new frozen evaluator smoke and 30 paired cases were not run;
there is no paired quality/latency claim. Raw smoke evidence is under
`artifacts/research/2026-09-09_mlx-search-recovery/`, with the full report at
`docs/research/2026-09-09_mlx-search-recovery.md` and plan at
`.plans/2026-09-09_mlx-search-recovery.md`.