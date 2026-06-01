from __future__ import annotations

import math

from ..domain import SearchResult
from ..math_utils import normalize
from ..providers import EmbeddingProvider
from ..store import VectorStore
from .retrieval_strategy import RetrievalStrategy


class MultiIndexVectorRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
        kind_limits: dict[str, int],
        kind_multipliers: dict[str, float] | None = None,
    ):
        self.provider = provider
        self.vector_store = vector_store
        self.kind_limits = {kind: limit for kind, limit in kind_limits.items() if limit > 0}
        self.kind_multipliers = {
            kind: multiplier
            for kind, multiplier in (kind_multipliers or {}).items()
            if multiplier > 0
        }

    def search(self, query: str, limit: int) -> list[SearchResult]:
        effective_limits = self._effective_limits(limit)
        if not effective_limits:
            return self.vector_store.search(normalize(self.provider.embed_query(query)), limit)
        query_vector = normalize(self.provider.embed_query(query))
        results: list[SearchResult] = []
        for kind, kind_limit in effective_limits.items():
            results.extend(self.vector_store.search_by_index_kind(query_vector, kind_limit, kind))
        return self._ranked(results, limit)

    def _effective_limits(self, limit: int) -> dict[str, int]:
        if self.kind_limits:
            return self.kind_limits
        return {kind: max(1, math.ceil(limit * multiplier)) for kind, multiplier in self.kind_multipliers.items()}

    def _ranked(self, results: list[SearchResult], limit: int) -> list[SearchResult]:
        by_id: dict[str, SearchResult] = {}
        for result in results:
            current = by_id.get(result.item.id)
            if current is None or result.score > current.score:
                by_id[result.item.id] = result
        ranked = sorted(by_id.values(), key=lambda result: (result.score, result.item.path), reverse=True)
        return ranked[:limit]
