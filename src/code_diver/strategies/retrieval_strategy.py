from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain import SearchResult


class RetrievalStrategy(ABC):
    @abstractmethod
    def search(self, query: str, limit: int) -> list[SearchResult]:
        raise NotImplementedError
