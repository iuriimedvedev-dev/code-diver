# MLX latency mitigation and bounded search evaluation — 2026-09-08

## Verdict

The isolated embedder experiment reproduced a large idle-delay effect in this
sitting. Three randomized OFF and three randomized ON blocks each used at least
60 seconds of controlled workload idle, a real dataset query, and an immediate
novel query. All 12 real requests and all 90 direct ON warm requests returned
finite 1024-dimensional vectors with HTTP 200.

The current `scripts/keep_services_warm.py` was **not** run: it unconditionally
starts both its embedder and reranker threads, so it cannot prove an embedder-
only mitigation without a source edit. The ON condition therefore means direct,
embedder-only API warm requests, not helper-script verification.

| Real request | OFF p50 / p95 | ON p50 / p95 | OFF n | ON n |
|---|---:|---:|---:|---:|
| First after 60 s idle | 2075.0 / 2191.7 ms | 26.1 / 27.8 ms | 3 | 3 |
| Immediate novel second | 13.8 / 14.1 ms | 15.7 / 16.7 ms | 3 | 3 |

These are descriptive small-sample measurements, not a controlled causal proof
of macOS eviction. Global system idle was not observable without privileged or
process-wide instrumentation. Health was recorded separately and was not used
as a warmth signal. Preflight memory evidence showed 45% system-wide free
memory, `vm.swapusage` used `21176.75M` of `22528.00M`, and `5196924` pages in
the compressor.

## Runtime identity and isolation

- Embedder: `http://127.0.0.1:8001`, model
  `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ`.
- CE: `http://127.0.0.1:18081`, model
  `Qwen3-Reranker-0.6B-Q4_K_M.gguf`.
- Qdrant: `http://127.0.0.1:6333`.
- No service restart, cache purge, package install, source edit, or unrelated
  process termination was performed.
- The direct embedder-config baseline attempt was rejected by the existing
  harness runtime-management guard before requests. It is retained under
  `rust-baseline-rejected-20260908T135900Z`; it is not benchmark evidence.
- The successful baseline retained the existing harness embedding config at
  `http://localhost:8001` because changing it to `127.0.0.1` triggers that
  guard. CE and Qdrant used direct IPv4 overrides through the verified function
  `__globals__` route.

## Fresh bounded search baseline

The existing `scripts/research_rust_full_eval.py` ran serially with a fresh
run name and `--max-pairs 30`. This is 30 distinct deterministic scheduled
pairs, 60 arm requests, with keepwarm OFF. The fixed native limits were
retrieval `360`, candidate/CE input `34`, and result `10`; no quality or
document budget was reduced. All 60 requests succeeded and all failures remain
represented in the denominator (zero failures in this run).

| Membership view | Arm | Attempted | Failures | Hit@10 | MRR@10 | Request p50 / p95 |
|---|---|---:|---:|---:|---:|---:|
| `full1065` | Python | 30 | 0 | 0.966667 | 0.966667 | 8041.0 / 15462.6 ms |
| `full1065` | Rust | 30 | 0 | 0.900000 | 0.776389 | 6614.8 / 9308.8 ms |
| `WHERE78` | Python | 1 | 0 | 1.000000 | 1.000000 | 4305.5 / 4305.5 ms |
| `WHERE78` | Rust | 1 | 0 | 1.000000 | 0.333333 | 3131.6 / 3131.6 ms |
| `mech150` | Python | 4 | 0 | 0.750000 | 0.750000 | 8120.4 / 12537.7 ms |
| `mech150` | Rust | 4 | 0 | 0.750000 | 0.583333 | 4980.0 / 9131.5 ms |

The `WHERE78` and `mech150` rows are overlapping membership views of the same
30 selected cases, not additional holdouts. Rust internal instrumentation had
only `total_ms`: p50 `6614.3 ms`, p95 `9308.6 ms`. Startup was separate from
request-wall time: Python `1775.71 ms`, Rust `5697.28 ms`. Search still used
the llama CE route; this report makes no MLX end-to-end claim.

## Exact commands

The plan was frozen before live runs in
`.plans/2026-09-08_mlx-latency-eval.md`. The bounded latency workload was an
inline `python3` heredoc, intentionally not materialized as a new source script;
its parameters were: output
`artifacts/research/2026-09-08_mlx-latency-eval/latency-blocks-20260908T135000Z.jsonl`,
seed `20260908`, three blocks, randomized OFF/ON order, 60-second idles,
2-second direct `POST` warm requests to `127.0.0.1:8001`, and 90-second request
timeouts. The original inline body was not materialized as a source file. The
following is a runnable replay with the same gates and design; use a new output
path because the retained raw file is immutable:

```bash
python3 - <<'PY'
import json, math, random, time, urllib.request
from pathlib import Path
out = Path("artifacts/research/2026-09-08_mlx-latency-eval/latency-replay.jsonl")
assert not out.exists(), out
queries = []
for line in Path("datasets/intellij_eval_1000.answer_sets.jsonl").read_text().splitlines():
    if line.strip():
        row = json.loads(line)
        if row.get("query"):
            queries.append({"id": row["id"], "query": row["query"]})
        if len(queries) == 12:
            break
rng = random.Random(20260908)
plans = []
for block in range(3):
    conditions = ["off", "on"]
    rng.shuffle(conditions)
    plans.append((block + 1, conditions, {"off": [2 * block, 2 * block + 1], "on": [6 + 2 * block, 7 + 2 * block]}))
def write(row):
    with out.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
def post(text, block, condition, kind):
    body = json.dumps({"model": "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ", "input": text}).encode()
    started = time.perf_counter()
    row = {"kind": kind, "block": block, "condition": condition}
    try:
        request = urllib.request.Request("http://127.0.0.1:8001/v1/embeddings", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode())
        vector = payload["data"][0]["embedding"]
        row.update(status=response.status, dimensions=len(vector), finite=all(math.isfinite(x) for x in vector))
    except Exception as exc:
        row.update(status=None, dimensions=None, finite=False, error=f"{type(exc).__name__}: {exc}")
    row["wall_ms"] = (time.perf_counter() - started) * 1000
    write(row)
for block, conditions, indices in plans:
    for condition in conditions:
        write({"kind": "block_start", "block": block, "condition": condition, "idle_s": 60, "global_idle_observable": False})
        end, next_warm = time.monotonic() + 60, time.monotonic()
        while time.monotonic() < end:
            if condition == "on" and time.monotonic() >= next_warm:
                post("warm", block, condition, "warm")
                next_warm += 2
            time.sleep(0.25)
        first, second = indices[condition]
        post(queries[first]["query"], block, condition, "real_first")
        post(queries[second]["query"], block, condition, "real_immediate_novel")
PY
```

The exact existing-test commands were:

```bash
PYTHONPATH=src:scripts .venv/bin/python -B scripts/test_research_rust_full_eval.py
PYTHONPATH=src .venv/bin/pytest -q tests/test_research_large_search_eval.py tests/test_research_latency_independence.py tests/test_research_ce_evidence.py
```

Results were `4/4` unittest cases and `25/25` pytest cases.

The successful baseline command used the existing harness with the verified
in-memory `main.__globals__` IPv4 override:

```bash
PYTHONPATH=src:scripts .venv/bin/python -B -c 'import dataclasses,runpy,sys; m=runpy.run_path("scripts/research_rust_full_eval.py",run_name="rust_eval_ipv4_bounded"); g=m["main"].__globals__; old_config=g["config"]; old_get_json=g["get_json"]; ce="http://127.0.0.1:18081/v1/rerank"; ce_models="http://127.0.0.1:18081/v1/models"; qdrant="http://127.0.0.1:6333"; g["config"]=lambda: (lambda c: dataclasses.replace(c,storage=dataclasses.replace(c.storage,qdrant=dataclasses.replace(c.storage.qdrant,url=qdrant)),cross_encoder_rerank=dataclasses.replace(c.cross_encoder_rerank,url=ce)))(old_config()); g["get_json"]=lambda url: old_get_json((qdrant+url[len("http://localhost:6333"):]) if url.startswith("http://localhost:6333") else (ce_models if url == "http://localhost:18081/v1/models" else url)); g["COMMAND"]=[g["BIN"],"--server","--catalog","/tmp/rust_catalog.jsonl","--graph","/tmp/rust_graph.jsonl","--model",g["MODEL"],"--embedding-url","http://localhost:8001/v1/embeddings","--qdrant-url",qdrant,"--ce-url",ce,"--retrieval-limit","360","--candidate-limit","34","--limit","10"]; sys.argv=["research_rust_full_eval.py","--run","bounded-20260908T140300Z","--seconds","900","--max-pairs","30"]; g["main"]()'
```

The immutable manifest records the complete effective native command and routes;
the copied baseline manifest is the authoritative runnable identity record.

## Evidence and hashes

| Artifact | SHA-256 |
|---|---|
| `preflight-20260908T134900Z.json` | `885ee0070e504eda28cf0ed46409f7a2178f4412d5d53d5f65a87bab3fbda097` |
| `latency-blocks-20260908T135000Z.jsonl` | `a9c51cbacd720f14550e7120283a7a2afa610a900e6f40503fe7f2875a483759` |
| bounded `manifest.json` | `188c3fc1d3604c9403a75c61d191d04d831045614cd158fa92973c2db181bd7e` |
| bounded `results.jsonl` | `740df60590e111de0e02b4cd338c726c484a8cd3eab88de75b2b819a61903985` |
| bounded `summary-*.json` | `20c052f3b624bed2fafb960873256810bc503a690e95e052ac41c97ed01b708c` |
| rejected direct-embedder `manifest.json` | `ab819c93a88938cfc5de9f2d15b84cb9d33609ae2a2e0268488be0f28a531c97` |

Raw evidence is under
`artifacts/research/2026-09-08_mlx-latency-eval/`. Prior reports and raw
artifacts were not rewritten.