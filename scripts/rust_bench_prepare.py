#!/usr/bin/env python3
"""Prepare data files for Rust benchmark and run it."""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CATALOG_SRC = BASE / ".code-diver" / "intellij-h37-jvm-graph.file-graph-catalog.json"
RUST_CATALOG = Path("/tmp") / "rust_catalog.jsonl"
RUST_GRAPH = Path("/tmp") / "rust_graph.jsonl"
RUST_QUERIES = Path("/tmp") / "rust_bench_queries.txt"
RESULTS_DIR = BASE / "artifacts" / "research" / "2026-09-06_rust-benchmark"
RUST_BIN = BASE / "native" / "code_diver_search_bin" / "target" / "release" / "code_diver_search_bin"
MODEL_PATH = BASE / "artifacts" / "ce_meta_ranker" / "ce_meta_ranker.lgb.txt"
DATASET_PATH = BASE / "datasets" / "intellij_eval_where_only.jsonl"


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load catalog
    print("=== Loading catalog ===")
    with open(CATALOG_SRC) as f:
        data = json.load(f)
    items = data["catalog"]["items"]
    print(f"  Items: {len(items)}")

    # 2. Convert to Rust JSONL format with pre-tokenized fields
    print("=== Converting to Rust JSONL ===")
    
    def tokenize(text):
        """Fast tokenization matching Python's tokenize_path."""
        parts = re.split(r'[^a-zA-Z0-9]+', text)
        result = []
        for part in parts:
            if not part:
                continue
            sub = re.split(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', part)
            for s in sub:
                s = s.strip()
                if s and len(s) >= 2:
                    result.append(s.lower())
        return result
    
    count = 0
    with open(RUST_CATALOG, "w") as out:
        for item_id, item in items.items():
            name = item.get("title", "")
            path = item.get("path", "")
            dir_path = "/".join(path.split("/")[:-1]) if path else ""
            content = item.get("content", "")
            rec = {
                "id": item.get("id", item_id),
                "path": path,
                "kind": item.get("metadata", {}).get("index_kind", ""),
                "name": name,
                "content": content,
                "symbols": [],
                "tokenized_name": tokenize(name),
                "tokenized_path": tokenize(path),
                "tokenized_dir": tokenize(dir_path),
                "tokenized_content": tokenize(content),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
    print(f"  Written: {count} items to {RUST_CATALOG}")
    size_mb = RUST_CATALOG.stat().st_size / (1024 * 1024)
    print(f"  Size: {size_mb:.1f} MB")

    # 3. Build graph adjacency JSONL
    print("=== Building graph adjacency JSONL ===")
    adj_data = data["catalog"]["adjacency"]["adjacency"]
    count = 0
    with open(RUST_GRAPH, "w") as out:
        for path, neighbors in adj_data.items():
            rec = {"path": path, "neighbors": neighbors}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
    print(f"  Written: {count} entries to {RUST_GRAPH}")
    size_mb = RUST_GRAPH.stat().st_size / (1024 * 1024)
    print(f"  Size: {size_mb:.1f} MB")

    # 4. Build benchmark queries
    print("=== Building benchmark queries ===")
    queries = []
    with open(DATASET_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                q = rec.get("query") or rec.get("question", "")
                if q:
                    queries.append(q)
    print(f"  Queries from WHERE-78: {len(queries)}")
    with open(RUST_QUERIES, "w") as out:
        for q in queries:
            out.write(q + "\n")

    # 5. Check Rust binary exists
    print("=== Checking Rust binary ===")
    if not RUST_BIN.exists():
        print(f"  ERROR: Rust binary not found at {RUST_BIN}")
        print("  Building...")
        subprocess.run(
            ["cargo", "build", "--release"],
            cwd=str(BASE / "native" / "code_diver_search_bin"),
            check=True,
        )
    else:
        print(f"  Found: {RUST_BIN}")

    # 6. Run benchmark
    print("=== Running Rust benchmark ===")
    n_queries = min(20, len(queries))
    cmd = [
        str(RUST_BIN),
        "--catalog", str(RUST_CATALOG),
        "--graph", str(RUST_GRAPH),
        "--model", str(MODEL_PATH),
        "--bench", str(RUST_QUERIES),
        "--bench-n", str(n_queries),
        "--ce-url", "http://localhost:18081/v1/rerank",
    ]
    print(f"  Command: {' '.join(cmd)}")
    print(f"  Queries: {n_queries}")

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - start

    # 7. Save results
    summary = {
        "exit_code": result.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "n_queries": n_queries,
        "stdout": result.stdout,
        "stderr": result.stderr[:5000] if result.stderr else "",
        "command": " ".join(cmd),
        "catalog_items": count,
        "graph_entries": len(adj_data),
    }

    with open(RESULTS_DIR / "results.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n  Exit code: {result.returncode}")
    print(f"  Elapsed: {elapsed:.2f}s")
    print(f"  Stdout ({len(result.stdout)} chars):")
    print(result.stdout[:2000])
    if result.stderr:
        print(f"  Stderr ({len(result.stderr)} chars):")
        print(result.stderr[:1000])

    print(f"\n=== Results saved to {RESULTS_DIR / 'results.json'} ===")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())