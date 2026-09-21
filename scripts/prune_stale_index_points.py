#!/usr/bin/env python3
"""Delete stale points (by item.id) from a Qdrant collection.

The ids file is the full only_in_index list, e.g. produced by diffing
scripts/audit_index_staleness.py output against a fresh scanner run
(see docs/research/2026-09-21_index-prune.md for the procedure).

Dry-run by default; pass --apply to delete. Verifies every requested id
exists before deleting and reports the count delta afterwards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--stale-ids", type=Path, required=True,
                        help="file with one item.id per line")
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default: dry run)")
    args = parser.parse_args()

    from qdrant_client import QdrantClient

    wanted = [line.strip() for line in args.stale_ids.read_text().splitlines() if line.strip()]
    print(f"stale ids requested: {len(wanted)}", flush=True)
    if not wanted:
        return 0

    client = QdrantClient(url=args.qdrant_url)
    before = client.count(collection_name=args.collection, exact=True).count
    print(f"collection points before: {before}", flush=True)

    id_to_point: dict[str, str] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=args.collection, limit=8192, offset=offset,
            with_payload=True, with_vectors=False)
        for point in points:
            item = (point.payload or {}).get("item") or {}
            item_id = str(item.get("id") or "")
            if item_id:
                id_to_point[item_id] = str(point.id)
        if offset is None:
            break

    missing = [i for i in wanted if i not in id_to_point]
    point_ids = [id_to_point[i] for i in wanted if i in id_to_point]
    print(f"matched points: {len(point_ids)}, missing ids: {len(missing)}", flush=True)
    for item_id in missing[:10]:
        print(f"  missing: {item_id}", flush=True)
    if missing:
        print("refusing: stale list does not match collection state", file=sys.stderr)
        return 1
    if len(set(point_ids)) != len(point_ids):
        print("refusing: duplicate point mapping", file=sys.stderr)
        return 1

    if not args.apply:
        print("dry run: pass --apply to delete", flush=True)
        return 0
    client.delete(collection_name=args.collection, points_selector=point_ids, wait=True)
    after = client.count(collection_name=args.collection, exact=True).count
    print(f"collection points after: {after} (delta {after - before})", flush=True)
    if after != before - len(point_ids):
        print("WARNING: unexpected count delta", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
