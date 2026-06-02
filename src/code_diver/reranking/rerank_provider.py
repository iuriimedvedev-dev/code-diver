from __future__ import annotations

from abc import ABC, abstractmethod

from .rerank_score import RerankScore


class RerankProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankScore]:
        raise NotImplementedError
