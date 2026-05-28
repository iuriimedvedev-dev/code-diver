from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain import CodeItem
from .index_store_error import IndexStoreError

SCHEMA_VERSION = 1


class IndexStore:
    def save(
        self,
        artifact: Path,
        *,
        root: Path,
        provider: str,
        model: str,
        dimensions: int,
        items: list[CodeItem],
        vectors: list[list[float]],
    ) -> None:
        if len(items) != len(vectors):
            raise IndexStoreError(f"Item/vector mismatch: {len(items)} items, {len(vectors)} vectors")

        artifact.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root": str(root.resolve()),
            "provider": provider,
            "model": model,
            "dimensions": dimensions,
            "items": [
                {
                    "item": item.to_json(),
                    "vector": vector,
                }
                for item, vector in zip(items, vectors)
            ],
        }
        artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self, artifact: Path) -> dict[str, Any]:
        if not artifact.exists():
            raise IndexStoreError(f"Index artifact not found: {artifact}")
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise IndexStoreError(
                f"Unsupported index schema {payload.get('schema_version')}; expected {SCHEMA_VERSION}"
            )
        return payload

    def load_items_and_vectors(self, artifact: Path) -> tuple[dict[str, Any], list[CodeItem], list[list[float]]]:
        payload = self.load(artifact)
        records = payload.get("items") or []
        items = [CodeItem.from_json(record["item"]) for record in records]
        vectors = [[float(value) for value in record["vector"]] for record in records]
        return payload, items, vectors
