from __future__ import annotations

from dataclasses import dataclass

from ..domain import CodeItem
from ..store import InMemoryVectorStore


@dataclass(frozen=True, slots=True)
class EphemeralDeepIndexResult:
    vector_store: InMemoryVectorStore
    items: list[CodeItem]
    build_ms: float
    temporary_vectors: int
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total <= 0:
            return 0.0
        return self.cache_hits / total
