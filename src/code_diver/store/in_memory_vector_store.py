from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain import CodeItem, SearchResult
from ..math_utils import dot, normalize
from .index_store_error import IndexStoreError
from .vector_store import VectorStore


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self.root: Path | None = None
        self.provider = ""
        self.model = ""
        self.dimensions = 0
        self.items: list[CodeItem] = []
        self.vectors: list[list[float]] = []

    def exists(self) -> bool:
        return bool(self.items)

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
        self.root = root.resolve()
        self.provider = provider
        self.model = model
        self.dimensions = dimensions
        self.items = list(items)
        self.vectors = [list(vector) for vector in vectors]

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
        }

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        normalized_query = normalize(query_vector)
        scored = [
            SearchResult(item=item, score=dot(normalized_query, normalize(vector)))
            for item, vector in zip(self.items, self.vectors, strict=True)
        ]
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:limit]

    def count_items(self) -> int:
        return len(self.items)
