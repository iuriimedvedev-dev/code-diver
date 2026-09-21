#!/usr/bin/env python3
"""Dump a fresh Rust-format catalog JSONL from the CURRENT checkout.

Unlike scripts/rust_bench_prepare.py (which reads the stale
.code-diver/intellij-h37-jvm-graph.file-graph-catalog.json snapshot), this runs
make_codebase_scanner over the live repo root, so ids/contents reflect the
current revision. Output record shape matches rust_bench_prepare.py exactly.

Usage: dump_rust_catalog.py --config CONFIG_YML --out PATH
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def tokenize(text: str) -> list[str]:
    parts = re.split(r"[^a-zA-Z0-9]+", text)
    result = []
    for part in parts:
        if not part:
            continue
        sub = re.split(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", part)
        for item in sub:
            item = item.strip()
            if item and len(item) >= 2:
                result.append(item.lower())
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from code_diver.cli import make_codebase_scanner
    from code_diver.config import ConfigLoader

    config = ConfigLoader().load(Path(args.config))
    scanner = make_codebase_scanner(config)
    count = 0
    with open(args.out, "w") as out:
        for item in scanner.scan(Path(config.root)):
            metadata = item.metadata or {}
            path = item.path or ""
            dir_path = "/".join(path.split("/")[:-1]) if path else ""
            name = item.title or ""
            content = item.content or ""
            rec = {
                "id": item.id,
                "path": path,
                "kind": metadata.get("index_kind", ""),
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
    print(f"wrote {count} items to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
