"""Compare a live Qdrant collection against what the CURRENT scanner would produce.

Why this exists: an index is a cached function of (repository contents, scanner code,
scanner config). Two of those three are invisible once the collection is written, so a
collection can silently stop matching the code that queries it. On 2026-08-12 the protogen
index turned out to predate a scanner change by sixteen minutes -- the change added
head-line/head-block truncation to `FileSummaryItemBuilder` and unified the two divergent
exclusion predicates in `CodebaseScanner`, the second of which changes *which files exist*
in the index at all.

Nothing in the pipeline notices. Retrieval against a stale collection returns confident,
well-formed, wrong-by-a-little results, and every downstream metric inherits the drift
without a single error in the log.

What this reports, per collection:
  * `only_in_index`  -- items the current scanner no longer produces (exclusion drift, or
                        files deleted from the repo). These are dead weight that can still
                        be retrieved and cited.
  * `only_in_scan`   -- items the current scanner produces that the index lacks. These are
                        unreachable: retrieval can never return them.
  * `content_differs`-- items present in both whose embedded text changed. The stored vector
                        no longer describes the current text.

Exit status is 0 even when drift is found: this is a measurement, not a gate. Read the
numbers and decide whether a reindex is warranted.

Usage:
    audit_index_staleness.py --config CONFIG_YML [--collection NAME] [--sample N]
                             [--json-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

from code_diver.cli import make_codebase_scanner
from code_diver.config import ConfigLoader


def load_config(path: Path):
    return ConfigLoader().load(path)


def resolve_collection(base_url: str, prefix: str) -> str:
    """Collections carry a `__staging_<uuid>` suffix the config never spells out."""
    response = requests.get(f"{base_url}/collections", timeout=30)
    response.raise_for_status()
    names = [c["name"] for c in response.json()["result"]["collections"]]
    exact = [n for n in names if n == prefix]
    if exact:
        return exact[0]
    matches = [n for n in names if n.startswith(f"{prefix}__staging_")]
    if not matches:
        raise SystemExit(f"no collection named {prefix} (or {prefix}__staging_*) in {base_url}")
    if len(matches) > 1:
        raise SystemExit(f"{prefix} is ambiguous: {matches}")
    return matches[0]


def scroll_items(base_url: str, collection: str) -> dict[str, str]:
    """id -> embedded content, for every point in the collection."""
    items: dict[str, str] = {}
    offset: Any = None
    while True:
        body: dict[str, Any] = {"limit": 2048, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        response = requests.post(
            f"{base_url}/collections/{collection}/points/scroll", json=body, timeout=120
        )
        response.raise_for_status()
        result = response.json()["result"]
        for point in result["points"]:
            item = point["payload"].get("item") or {}
            item_id = str(item.get("id") or "")
            if item_id:
                items[item_id] = str(item.get("content") or "")
        offset = result.get("next_page_offset")
        if offset is None:
            break
        print(f"  scrolled {len(items)}", file=sys.stderr, flush=True)
    return items


def scan_items(config) -> dict[str, str]:
    scanner = make_codebase_scanner(config)
    produced: dict[str, str] = {}
    for item in scanner.scan(Path(config.root)):
        produced[str(item.id)] = str(item.content or "")
    return produced


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--collection", default=None, help="override config's collection name")
    parser.add_argument("--sample", type=int, default=3, help="differing items to print")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    if args.json_out is not None and args.json_out.exists():
        raise SystemExit(f"refusing to overwrite existing {args.json_out}")

    config = load_config(args.config)
    base_url = config.storage.qdrant.url.rstrip("/")
    prefix = args.collection or config.storage.qdrant.collection
    collection = resolve_collection(base_url, prefix)

    print(f"collection : {collection}", file=sys.stderr)
    print(f"root       : {config.root}", file=sys.stderr)
    indexed = scroll_items(base_url, collection)
    print(f"indexed    : {len(indexed)} items", file=sys.stderr)
    scanned = scan_items(config)
    print(f"scanned now: {len(scanned)} items", file=sys.stderr)

    only_index = sorted(set(indexed) - set(scanned))
    only_scan = sorted(set(scanned) - set(indexed))
    shared = sorted(set(indexed) & set(scanned))
    differs = [i for i in shared if indexed[i] != scanned[i]]

    total = max(len(indexed), 1)
    report = {
        "collection": collection,
        "root": str(config.root),
        "indexed_items": len(indexed),
        "scanned_items": len(scanned),
        "only_in_index": len(only_index),
        "only_in_scan": len(only_scan),
        "shared": len(shared),
        "content_differs": len(differs),
        "drift_rate": (len(only_index) + len(only_scan) + len(differs)) / total,
        "only_in_index_sample": only_index[: args.sample],
        "only_in_scan_sample": only_scan[: args.sample],
        "content_differs_sample": differs[: args.sample],
    }

    print(f"\nindexed          {report['indexed_items']}")
    print(f"scanner produces {report['scanned_items']}")
    print(f"only in index    {report['only_in_index']}  (stale, still retrievable)")
    print(f"only in scan     {report['only_in_scan']}  (unreachable, never retrievable)")
    print(f"content differs  {report['content_differs']} of {report['shared']} shared")
    print(f"drift rate       {report['drift_rate']:.4f}")

    for item_id in differs[: args.sample]:
        print(f"\n--- {item_id}")
        print(f"  indexed: {indexed[item_id][:220]!r}")
        print(f"  now    : {scanned[item_id][:220]!r}")

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
