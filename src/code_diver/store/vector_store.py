from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..domain import CodeItem, SearchResult


class VectorStore(ABC):
    @abstractmethod
    def exists(self) -> bool:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def metadata(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        raise NotImplementedError

    def search_by_index_kind(self, query_vector: list[float], limit: int, index_kind: str) -> list[SearchResult]:
        return [
            result
            for result in self.search(query_vector, limit * 10)
            if str(result.item.metadata.get("index_kind") or "") == index_kind
        ][:limit]
