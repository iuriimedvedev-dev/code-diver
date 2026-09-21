#!/usr/bin/env python3
"""Incrementally update a Qdrant code index: embed + upsert only what changed.

Unlike `code-diver index [--update-index]` (always a full rescan + re-embed of
every item into a staging collection), this script:

1. scrolls existing points: item.id -> (point id, embedded content),
2. scans the current repo (no embeddings),
3. diffs: deleted (indexed, not scanned) -> delete points;
           added (scanned, not indexed) -> embed + upsert;
           changed (shared id, content differs) -> re-embed + upsert;
           unchanged -> skipped entirely (this is the saving vs full rebuild).

The upsert path reuses QdrantVectorStore.append, so point ids and payloads are
byte-identical in construction to the full-indexing path. Deletes go through
the store client against the same (alias-resolved) collection.

Dry-run by default; pass --apply to write. Exit nonzero on any inconsistency
(match failures, count mismatch, dimension mismatch).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def load_config(path: Path):
    from code_diver.config import ConfigLoader

    return ConfigLoader().load(path)


def scroll_indexed(qdrant_url: str, collection: str) -> dict[str, tuple[str, str]]:
    """item.id -> (point id, embedded content) for every point."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=qdrant_url)
    items: dict[str, tuple[str, str]] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection, limit=8192, offset=offset,
            with_payload=True, with_vectors=False)
        for point in points:
            item = (point.payload or {}).get("item") or {}
            item_id = str(item.get("id") or "")
            if item_id:
                items[item_id] = (str(point.id), str(item.get("content") or ""))
        if offset is None:
            break
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/intellij/intellij-h91a-meta-ranker.yml")
    parser.add_argument("--apply", action="store_true",
                        help="actually write (default: dry run)")
    args = parser.parse_args()

    from code_diver.cli import make_codebase_scanner, make_vector_store
    from code_diver.providers.embedding_provider_builder import make_embedding_provider
    from code_diver.services.embedding_text_preparer import EmbeddingTextPreparer
    from code_diver.services.parallel_embedding_service import ParallelEmbeddingService

    config = load_config(Path(args.config))
    root = Path(config.root)
    qdrant_url = config.storage.qdrant.url
    collection = config.storage.qdrant.collection

    started = time.perf_counter()
    indexed = scroll_indexed(qdrant_url, collection)
    print(f"indexed points: {len(indexed)}", flush=True)

    scanner = make_codebase_scanner(config)
    scanned = {str(item.id): item for item in scanner.scan(root)}
    print(f"scanned items: {len(scanned)}", flush=True)

    indexed_ids = set(indexed)
    scanned_ids = set(scanned)
    deleted_ids = sorted(indexed_ids - scanned_ids)
    added_ids = sorted(scanned_ids - indexed_ids)
    changed_ids = sorted(i for i in indexed_ids & scanned_ids
                         if indexed[i][1] != str(scanned[i].content or ""))
    print(f"deleted: {len(deleted_ids)}, added: {len(added_ids)}, "
          f"changed: {len(changed_ids)}, unchanged: "
          f"{len(indexed_ids & scanned_ids) - len(changed_ids)}", flush=True)
    if not args.apply:
        print("dry run: pass --apply to write", flush=True)
        return 0
    if not deleted_ids and not added_ids and not changed_ids:
        print("index already in sync, nothing to do", flush=True)
        return 0

    vector_store = make_vector_store(config)
    try:
        provider = make_embedding_provider(config)
        dimensions = provider.dimensions
        if not dimensions:
            metadata = vector_store.metadata()
            dimensions = int(metadata.get("dimensions") or 0)
        if not dimensions:
            print("cannot determine vector dimensions", file=sys.stderr)
            return 1

        dirty_ids = added_ids + changed_ids
        if dirty_ids:
            from code_diver.services.indexing_options import IndexingOptions

            options = IndexingOptions(
                embedding_batch_size=config.embedding.batch_size,
                embedding_workers=config.embedding.workers,
                embedding_max_input_chars=config.embedding.max_input_chars,
                embedding_max_input_tokens=config.embedding.max_input_tokens,
                embedding_token_safety_margin=config.embedding.token_safety_margin,
                progress=False,
            )
            preparer = EmbeddingTextPreparer(
                options.embedding_max_input_chars,
                max_input_tokens=options.embedding_max_input_tokens,
                token_safety_margin=options.embedding_token_safety_margin,
            )
            items = [scanned[i] for i in dirty_ids]
            texts = [preparer.prepare(item) for item in items]
            vectors = ParallelEmbeddingService(
                provider, batch_size=options.embedding_batch_size,
                workers=options.embedding_workers).embed_documents(texts)
            if not provider.dimensions and vectors:
                provider.dimensions = len(vectors[0])
            vector_store.append(
                root=root, provider=provider.name, model=provider.model,
                dimensions=dimensions, items=items, vectors=vectors)
            print(f"upserted: {len(items)}", flush=True)

        if deleted_ids:
            point_ids = [indexed[i][0] for i in deleted_ids]
            vector_store.client.delete(
                collection_name=collection, points_selector=point_ids, wait=True)
            print(f"deleted: {len(point_ids)}", flush=True)
    finally:
        from code_diver.cli import close_vector_store

        close_vector_store(vector_store)

    elapsed = time.perf_counter() - started
    print(f"done in {elapsed:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
