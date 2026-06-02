from __future__ import annotations

from threading import Lock

from .embedding_provider import EmbeddingProvider


class QueryCachingEmbeddingProvider(EmbeddingProvider):
    def __init__(self, delegate: EmbeddingProvider):
        self.delegate = delegate
        self.name = delegate.name
        self.model = delegate.model
        self.dimensions = delegate.dimensions
        self._query_cache: dict[str, list[float]] = {}
        self._lock = Lock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.delegate.embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        with self._lock:
            cached = self._query_cache.get(query)
            if cached is not None:
                return cached
        vector = self.delegate.embed_query(query)
        with self._lock:
            self._query_cache[query] = vector
        return vector
