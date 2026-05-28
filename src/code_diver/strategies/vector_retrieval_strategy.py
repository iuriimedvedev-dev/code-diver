from __future__ import annotations

from ..domain import SearchResult
from ..providers import EmbeddingProvider
from ..services.retrieval_service import RetrievalService
from ..store import VectorStore
from .retrieval_strategy import RetrievalStrategy


class VectorRetrievalStrategy(RetrievalStrategy):
    def __init__(
        self,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
        retrieval_service: RetrievalService | None = None,
    ):
        self.provider = provider
        self.vector_store = vector_store
        self.retrieval_service = retrieval_service or RetrievalService()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.retrieval_service.search(self.provider, query, self.vector_store, limit)
