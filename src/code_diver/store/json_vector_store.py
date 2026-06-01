from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain import CodeItem, SearchResult
from ..math_utils import dot, normalize
from ..settings import SchemaKey
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
            SchemaKey.SCHEMA_VERSION.value: SCHEMA_VERSION,
            SchemaKey.CREATED_AT.value: datetime.now(timezone.utc).isoformat(),
            SchemaKey.ROOT.value: str(root.resolve()),
            SchemaKey.PROVIDER.value: provider,
            SchemaKey.MODEL.value: model,
            SchemaKey.DIMENSIONS.value: dimensions,
            SchemaKey.ITEMS.value: [
                {
                    SchemaKey.ITEM.value: item.to_json(),
                    SchemaKey.VECTOR.value: vector,
                }
                for item, vector in zip(items, vectors)
            ],
        }
        self.artifact.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def metadata(self) -> dict[str, Any]:
        payload = self._load()
        return {
            SchemaKey.PROVIDER.value: payload[SchemaKey.PROVIDER.value],
            SchemaKey.MODEL.value: payload[SchemaKey.MODEL.value],
            SchemaKey.DIMENSIONS.value: payload[SchemaKey.DIMENSIONS.value],
        }

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        _, items, vectors = self.load_items_and_vectors()
        return self._search_items(query_vector, items, vectors, limit)

    def search_by_index_kind(self, query_vector: list[float], limit: int, index_kind: str) -> list[SearchResult]:
        _, items, vectors = self.load_items_and_vectors()
        filtered_items: list[CodeItem] = []
        filtered_vectors: list[list[float]] = []
        for item, vector in zip(items, vectors):
            if str(item.metadata.get("index_kind") or "") != index_kind:
                continue
            filtered_items.append(item)
            filtered_vectors.append(vector)
        return self._search_items(query_vector, filtered_items, filtered_vectors, limit)

    def _search_items(
        self,
        query_vector: list[float],
        items: list[CodeItem],
        vectors: list[list[float]],
        limit: int,
    ) -> list[SearchResult]:
        normalized_query = normalize(query_vector)
        scored = [
            SearchResult(item=item, score=dot(normalized_query, normalize(vector)))
            for item, vector in zip(items, vectors)
        ]
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:limit]

    def load_items_and_vectors(self) -> tuple[dict[str, Any], list[CodeItem], list[list[float]]]:
        payload = self._load()
        records = payload.get(SchemaKey.ITEMS.value) or []
        items = [CodeItem.from_json(record[SchemaKey.ITEM.value]) for record in records]
        vectors = [[float(value) for value in record[SchemaKey.VECTOR.value]] for record in records]
        return payload, items, vectors

    def count_items(self) -> int:
        _, items, _ = self.load_items_and_vectors()
        return len(items)

    def _load(self) -> dict[str, Any]:
        if not self.artifact.exists():
            raise IndexStoreError(f"Index artifact not found: {self.artifact}")
        payload = json.loads(self.artifact.read_text(encoding="utf-8"))
        if payload.get(SchemaKey.SCHEMA_VERSION.value) != SCHEMA_VERSION:
            raise IndexStoreError(
                f"Unsupported index schema {payload.get(SchemaKey.SCHEMA_VERSION.value)}; expected {SCHEMA_VERSION}"
            )
        return payload
