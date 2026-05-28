from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain import CodeItem, SearchResult
from ..math_utils import dot, normalize
from .index_store_error import IndexStoreError
from .vector_store import VectorStore

SCHEMA_VERSION = 1


class JsonVectorStore(VectorStore):
    def __init__(self, artifact: Path):
        self.artifact = artifact

    def exists(self) -> bool:
        return self.artifact.exists()

    def save(
        self,
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

        self.artifact.parent.mkdir(parents=True, exist_ok=True)
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
        self.artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def metadata(self) -> dict[str, Any]:
        payload = self._load()
        return {
            "provider": payload["provider"],
            "model": payload["model"],
            "dimensions": payload["dimensions"],
        }

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        _, items, vectors = self.load_items_and_vectors()
        normalized_query = normalize(query_vector)
        scored = [
            SearchResult(item=item, score=dot(normalized_query, normalize(vector)))
            for item, vector in zip(items, vectors)
        ]
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:limit]

    def load_items_and_vectors(self) -> tuple[dict[str, Any], list[CodeItem], list[list[float]]]:
        payload = self._load()
        records = payload.get("items") or []
        items = [CodeItem.from_json(record["item"]) for record in records]
        vectors = [[float(value) for value in record["vector"]] for record in records]
        return payload, items, vectors

    def _load(self) -> dict[str, Any]:
        if not self.artifact.exists():
            raise IndexStoreError(f"Index artifact not found: {self.artifact}")
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise IndexStoreError(
                f"Unsupported index schema {payload.get('schema_version')}; expected {SCHEMA_VERSION}"
            )
        return payload
