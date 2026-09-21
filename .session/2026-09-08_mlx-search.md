# MLX search handoff — 2026-09-08

## Status

The ready-made upstream `vllm-metal 0.28.0` Qwen3 reranker path works
semantically only with the explicit official chat template. It was not
promoted: the retained integrated run has `15` matched pairs plus one extra
Rust/MLX failure, with MLX behind Python on paired hit@10 and MRR and no speed
win. The owned endpoint was stopped; `18081`, `8001`, and `6333` were left
untouched.

## Evidence

- Run: `artifacts/research/2026-09-08_mlx-search/qwen3-reranker-vllm-metal-official-template-30pairs-v2/`
- Journal: `62` events, `31` results, `16` distinct cases, no pending entries.
- Python: `15/15` completed, hit@10/MRR `0.9333333333 / 0.9333333333`, p50/p95 `97144.09 / 107056.66 ms`.
- Rust/MLX: `16` attempts, one failure, failure-inclusive hit@10/MRR `0.8125 / 0.6979166667`, p50/p95 `98905.49 / 176770.29 ms`.
- Matched 15-pair deltas: hit@10 `-0.0666666667`, MRR `-0.1888888889`.
- Failure index `30` remains retained and was not retried.
- Raw bounded diagnosis: `artifacts/research/2026-09-08_mlx-search/bounded-diagnosis-20260908T2300.jsonl`.
- Correct manifest embedding prefix probe: timeout `30.44 s`.
- Tiny two-document llama CE: HTTP `200` in `15.30 s`.
- Tiny two-document official MLX CE: timeout `30.00 s`.
- Memory before cleanup: `67%` free, swap `64327.88 MiB / 65536 MiB`; vLLM logged `Running: 1`, `Waiting: 12`.

## Configuration caveat

The actual frozen manifest used Python CE `http://localhost:18081/v1/rerank`
and embedding `http://localhost:8001/v1/embeddings`; only the Rust CE command
was replaced in memory with `http://127.0.0.1:18083/v1/rerank`. Therefore the
run is not proof of the requested direct-IPv4 Python baseline. The exact launch
and evaluation commands, including the corrected single-snapshot model path,
are recorded in `docs/research/2026-09-08_mlx-search.md`.

## Cleanup

Owned PIDs `30097`, `30098`, `30291`, and `30294` were the only service/workers
targeted. Port `18083` is closed; `30294` remained only as a zombie entry with
no listener. No unrelated process was stopped.

## Recommendation

Do not resume the current run for acceptance. If a follow-up is authorized,
create a new frozen run with explicit IPv4 URLs for both baselines and the
embedding service, eliminate swap/queue contention, and first run the same
bounded probes before any additional paired workload. Keep the same retrieval
`360`, CE `34`, and result `10` budgets.