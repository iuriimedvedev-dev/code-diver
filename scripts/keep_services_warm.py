#!/usr/bin/env python3
"""Keep the embedder (:8001) and reranker (:8081) resident by pinging them.

Neither server unloads its model on purpose -- `vllm serve` and `llama-server` have no idle
or TTL flag to turn off (see scripts/serve_embedder.sh and scripts/serve_reranker.sh, which
are the canonical launch commands). The eviction is done TO them, by macOS: with swap at
21.6/22.5 GB and 3.8M pages in the compressor, an idle server's working set -- process pages
and, far more expensively, its Metal residency -- is reclaimed within seconds.

Measured on the embedder, single minimal request, same sitting:

    back-to-back        0.010 s
    after  2 s idle     0.24 s
    after 30 s idle     0.23 s
    after 45 s idle     2.25 s
    fully cold          2.47 s

A pipeline query spends ~15 s in stages that do not touch the embedder, so by the time the
next query needs it, it has ALWAYS been evicted -- which is the entire `embed_query ~= 3.5 s`
line, against 12 ms warm. The reranker degrades far less (0.021 s warm, 0.060 s after 30 s),
so it is pinged at a longer interval; its in-pipeline cost is contention, not eviction.

The penalty appears at gaps as short as 2 s, so the default embedder interval is 1 s. Each
ping costs ~12 ms of a single token, i.e. ~1% duty cycle -- cheaper than one cold start per
query by two orders of magnitude.

Run it alongside any latency-sensitive workload and stop it with Ctrl-C when done:

    python scripts/keep_services_warm.py                  # foreground
    python scripts/keep_services_warm.py --quiet &        # background, then `kill %1`

This is a latency fix only. It sends a fixed one-token payload to a separate connection and
never touches the retrieval path, so ranking and quality metrics are unaffected.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request

EMBEDDER_URL = "http://127.0.0.1:8001/v1/embeddings"
EMBEDDER_MODEL = "mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ"
RERANKER_URL = "http://127.0.0.1:8081/rerank"
PING_TEXT = "warm"


def post(url: str, payload: dict, timeout: float) -> float:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()
    return (time.perf_counter() - started) * 1000


def ping_loop(
    name: str, url: str, payload: dict, interval: float, timeout: float, quiet: bool
) -> None:
    while True:
        try:
            elapsed = post(url, payload, timeout)
            if not quiet:
                print(f"{name} {elapsed:7.1f} ms", flush=True)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            # A server that is down is not this script's problem to fix; keep trying so the
            # pinger survives a restart of either service without being restarted itself.
            print(f"{name} unreachable: {error}", file=sys.stderr, flush=True)
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedder-interval", type=float, default=1.0)
    parser.add_argument("--reranker-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    targets = [
        (
            "embedder",
            EMBEDDER_URL,
            {"model": EMBEDDER_MODEL, "input": PING_TEXT},
            args.embedder_interval,
        ),
        (
            "reranker",
            RERANKER_URL,
            {"query": PING_TEXT, "documents": [PING_TEXT], "top_n": 1},
            args.reranker_interval,
        ),
    ]
    for name, url, payload, interval in targets:
        thread = threading.Thread(
            target=ping_loop,
            args=(name, url, payload, interval, args.timeout, args.quiet),
            daemon=True,
        )
        thread.start()

    print("keeping :8001 and :8081 warm -- Ctrl-C to stop", file=sys.stderr, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
