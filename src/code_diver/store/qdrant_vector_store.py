from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from ..domain import CodeItem, SearchResult
from .vector_store import VectorStore


class QdrantVectorStore(VectorStore):
    def __init__(
        self,
        *,
        url: str = "http://localhost:6333",
        location: str | None = None,
        collection: str = "code_diver",
        api_key: str | None = None,
        api_key_env: str | None = "QDRANT_API_KEY",
        batch_size: int = 64,
    ):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install dependencies with `uv sync` before using Qdrant storage.") from exc

        resolved_key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
        if location:
            self.client = QdrantClient(location=location)
        else:
            self.client = QdrantClient(url=url, api_key=resolved_key)
        self.collection = collection
        self.batch_size = batch_size

    def exists(self) -> bool:
        return bool(self.client.collection_exists(self.collection))

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
            raise ValueError(f"Item/vector mismatch: {len(items)} items, {len(vectors)} vectors")

        from qdrant_client import models

        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
        )

        points = [
            models.PointStruct(
                id=self._point_id(item.id),
                vector=vector,
                payload={
                    "item": item.to_json(),
                    "root": str(root.resolve()),
                    "provider": provider,
                    "model": model,
                    "dimensions": dimensions,
                },
            )
            for item, vector in zip(items, vectors)
        ]
        for offset in range(0, len(points), self.batch_size):
            self.client.upsert(collection_name=self.collection, points=points[offset : offset + self.batch_size])

    def metadata(self) -> dict[str, Any]:
        points, _ = self.client.scroll(collection_name=self.collection, limit=1, with_payload=True, with_vectors=False)
        if not points:
            return {}
        payload = points[0].payload or {}
        return {
            "provider": payload.get("provider"),
            "model": payload.get("model"),
            "dimensions": payload.get("dimensions"),
        }

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
        return [
            SearchResult(item=CodeItem.from_json((point.payload or {})["item"]), score=float(point.score))
            for point in response.points
        ]

    def _point_id(self, item_id: str) -> str:
        return uuid.uuid5(uuid.NAMESPACE_URL, item_id).hex
