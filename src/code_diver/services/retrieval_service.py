from __future__ import annotations

from ..domain import CodeItem, SearchResult
from ..math_utils import dot, normalize
from ..providers import EmbeddingProvider


class RetrievalService:
    def search(
        self,
        provider: EmbeddingProvider,
        query: str,
        items: list[CodeItem],
        vectors: list[list[float]],
        limit: int,
    ) -> list[SearchResult]:
        query_vector = normalize(provider.embed_query(query))
        scored = [
            SearchResult(item=item, score=dot(query_vector, normalize(vector)))
            for item, vector in zip(items, vectors)
        ]
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:limit]
