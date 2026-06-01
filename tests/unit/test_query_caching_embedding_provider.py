from __future__ import annotations

from code_diver.providers.query_caching_embedding_provider import QueryCachingEmbeddingProvider


class FakeEmbeddingProvider:
    name = "fake"
    model = "fake-model"
    dimensions = 2

    def __init__(self):
        self.query_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0] for text in texts]

    def embed_query(self, query: str) -> list[float]:
        self.query_calls += 1
        return [float(len(query)), float(self.query_calls)]


def test_query_caching_embedding_provider_reuses_query_vectors() -> None:
    delegate = FakeEmbeddingProvider()
    provider = QueryCachingEmbeddingProvider(delegate)

    assert provider.embed_query("auth") == [4.0, 1.0]
    assert provider.embed_query("auth") == [4.0, 1.0]
    assert provider.embed_query("commands") == [8.0, 2.0]
    assert delegate.query_calls == 2


def test_query_caching_embedding_provider_delegates_documents() -> None:
    delegate = FakeEmbeddingProvider()
    provider = QueryCachingEmbeddingProvider(delegate)

    assert provider.embed_documents(["a", "abcd"]) == [[1.0, 0.0], [4.0, 0.0]]
