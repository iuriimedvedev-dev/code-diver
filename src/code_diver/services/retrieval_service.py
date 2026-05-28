from __future__ import annotations

from ..domain import SearchResult
from ..math_utils import normalize
from ..providers import EmbeddingProvider
from ..store import VectorStore


class RetrievalService:
    def search(
        self,
        provider: EmbeddingProvider,
        query: str,
        vector_store: VectorStore,
        limit: int,
    ) -> list[SearchResult]:
        query_vector = normalize(provider.embed_query(query))
        return vector_store.search(query_vector, limit)
