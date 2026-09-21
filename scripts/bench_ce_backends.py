#!/usr/bin/env python3
"""Compare CE rerank backends on one fixed 34-document payload.

Runs the same query+documents from
``artifacts/research/2026-09-08_metal-runtime/payloads_v2.json`` through
llama.cpp (default ``http://127.0.0.1:18081/v1/rerank``) and the vLLM-metal
pooling server (default ``http://127.0.0.1:18083/rerank``), then reports wall
time, top-N overlap, and score deltas.

Health gate: both services must answer ``GET <base>/v1/models`` first.
Otherwise nothing is sent and the script exits 2 with start instructions --
see ``scripts/serve_mlx_ce.sh`` (vLLM-metal) and your llama.cpp launcher for
port 18081.

Exit codes: 0 = compared (results JSON written), 2 = skipped (service down).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PAYLOAD = (
    REPO_ROOT / "artifacts/research/2026-09-08_metal-runtime/payloads_v2.json"
)
DEFAULT_LLAMA_URL = "http://127.0.0.1:18081/v1/rerank"
DEFAULT_LLAMA_MODEL = "Qwen3-Reranker-0.6B-Q4_K_M.gguf"
DEFAULT_MLX_URL = "http://127.0.0.1:18083/rerank"
DEFAULT_MLX_MODEL = "mlx-community/Qwen3-Reranker-0.6B-4bit"


def rerank_base_url(rerank_url: str) -> str:
    """Strip a trailing /v1/rerank or /rerank to get the server base URL."""
    base = rerank_url.rstrip("/")
    if base.endswith("/v1/rerank"):
        return base[: -len("/v1/rerank")]
    if base.endswith("/rerank"):
        return base[: -len("/rerank")]
    return base


def health_check(rerank_url: str, timeout: float) -> tuple[bool, str]:
    """Return (ok, detail) for GET <base>/v1/models."""
    url = rerank_base_url(rerank_url) + "/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
        return True, f"HTTP {response.status} {body[:160]}"
    except Exception as exc:  # noqa: BLE001 -- detail string is the point
        return False, f"{type(exc).__name__}: {exc}"


def post_rerank(
    url: str, model: str, query: str, documents: list[str], timeout: float
) -> tuple[dict[int, float], float, dict]:
    """POST one rerank batch; return (scores_by_index, wall_seconds, usage)."""
    payload = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer local"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"POST {url} -> HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
        ) from exc
    wall = time.perf_counter() - started
    results = raw.get("results", raw.get("data", []))
    scores = {}
    for entry in results:
        score = entry.get("relevance_score", entry.get("score"))
        if entry.get("index") is not None and score is not None:
            scores[int(entry["index"])] = float(score)
    if len(scores) != len(documents):
        raise RuntimeError(
            f"POST {url}: got {len(scores)} indexed scores for {len(documents)} documents"
        )
    return scores, wall, raw.get("usage", {})


def top_n_indices(scores: dict[int, float], n: int) -> list[int]:
    """Document indices of the top-N scores, best first (ties -> lower index)."""
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [index for index, _ in ordered[:n]]


def compare_rankings(
    llama_scores: dict[int, float], mlx_scores: dict[int, float], top_n: int
) -> dict:
    """Overlap and deltas between two full score maps over the same documents."""
    if set(llama_scores) != set(mlx_scores):
        raise ValueError("score maps cover different document sets")
    llama_top = top_n_indices(llama_scores, top_n)
    mlx_top = top_n_indices(mlx_scores, top_n)
    overlap = len(set(llama_top) & set(mlx_top))
    deltas = [abs(llama_scores[i] - mlx_scores[i]) for i in llama_scores]
    return {
        "top_n": top_n,
        "llama_top": llama_top,
        "mlx_top": mlx_top,
        "top_overlap": overlap,
        "max_abs_delta": max(deltas) if deltas else 0.0,
        "mean_abs_delta": sum(deltas) / len(deltas) if deltas else 0.0,
        "max_abs_delta_index": max(llama_scores, key=lambda i: abs(llama_scores[i] - mlx_scores[i])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    parser.add_argument("--caps", default="850,2400",
                        help="comma-separated payload caps to run (default: 850,2400)")
    parser.add_argument("--llama-url", default=DEFAULT_LLAMA_URL)
    parser.add_argument("--llama-model", default=DEFAULT_LLAMA_MODEL)
    parser.add_argument("--mlx-url", default=DEFAULT_MLX_URL)
    parser.add_argument("--mlx-model", default=DEFAULT_MLX_MODEL)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--health-timeout", type=float, default=10.0)
    parser.add_argument("--out", default="",
                        help="results JSON path (default: artifacts/research/<date>_ce-backend-bench/)")
    args = parser.parse_args()

    payloads = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    caps = [c.strip() for c in args.caps.split(",") if c.strip()]
    for cap in caps:
        if cap not in payloads or len(payloads[cap]["documents"]) != 34:
            print(f"payload {args.payload} has no 34-doc entry for cap {cap!r}", file=sys.stderr)
            return 2

    backends = {"llama": args.llama_url, "mlx": args.mlx_url}
    health = {name: health_check(url, args.health_timeout) for name, url in backends.items()}
    down = {name: detail for name, (ok, detail) in health.items() if not ok}
    if down:
        for name, detail in down.items():
            print(f"{name} ({backends[name]}) DOWN: {detail}", file=sys.stderr)
        print(
            "\nRefusing to compare with a backend down. To run:\n"
            "  1. Start llama.cpp CE on :18081 (batch 2048, ctx 40960, "
            "Qwen3-Reranker-0.6B-Q4_K_M.gguf).\n"
            "  2. Start vLLM-metal CE: bash scripts/serve_mlx_ce.sh "
            "(pooling, port 18083).\n"
            f"  3. Re-run: python scripts/{Path(__file__).name} --caps {args.caps}",
            file=sys.stderr,
        )
        return 2

    report: dict = {
        "payload": str(args.payload),
        "llama": {"url": args.llama_url, "model": args.llama_model},
        "mlx": {"url": args.mlx_url, "model": args.mlx_model},
        "caps": {},
    }
    for cap in caps:
        entry = payloads[cap]
        query, documents = entry["query"], entry["documents"]
        llama_scores, llama_wall, llama_usage = post_rerank(
            args.llama_url, args.llama_model, query, documents, args.timeout)
        mlx_scores, mlx_wall, mlx_usage = post_rerank(
            args.mlx_url, args.mlx_model, query, documents, args.timeout)
        comparison = compare_rankings(llama_scores, mlx_scores, args.top_n)
        report["caps"][cap] = {
            "document_count": len(documents),
            "llama_wall_seconds": llama_wall,
            "mlx_wall_seconds": mlx_wall,
            "llama_usage": llama_usage,
            "mlx_usage": mlx_usage,
            **comparison,
        }
        print(
            f"cap {cap}: llama {llama_wall:.2f}s vs mlx {mlx_wall:.2f}s | "
            f"top-{args.top_n} overlap {comparison['top_overlap']}/{args.top_n} | "
            f"max|delta| {comparison['max_abs_delta']:.4f} "
            f"(idx {comparison['max_abs_delta_index']})",
            flush=True,
        )

    out = Path(args.out) if args.out else (
        REPO_ROOT / "artifacts/research/2026-09-21_ce-backend-bench/results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
