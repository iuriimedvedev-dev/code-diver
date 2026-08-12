from __future__ import annotations

import pytest

from code_diver.domain import CodeItem, SearchResult
from code_diver.strategies.multi_index_vector_retrieval_strategy import MultiIndexVectorRetrievalStrategy

pytestmark = pytest.mark.unit


class FakeEmbeddingProvider:
    name = "fake"
    model = "fake"
    dimensions = 2

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        return []

    def search_by_index_kind(self, query_vector: list[float], limit: int, index_kind: str) -> list[SearchResult]:
        self.calls.append((index_kind, limit))
        return [
            SearchResult(
                item=CodeItem(
                    id=f"{index_kind}-item",
                    path=f"src/{index_kind}.py",
                    title=index_kind,
                    content=index_kind,
                    metadata={"index_kind": index_kind},
                ),
                score=0.5 if index_kind == "chunk" else 0.9,
            )
        ]


def test_multi_index_vector_retrieval_uses_configured_kind_quotas() -> None:
    store = FakeVectorStore()
    strategy = MultiIndexVectorRetrievalStrategy(
        FakeEmbeddingProvider(),
        store,
        {"chunk": 20, "symbol": 5},
    )

    results = strategy.search("where is auth?", limit=10)

    assert store.calls == [("chunk", 20), ("symbol", 5)]
    assert [result.item.metadata["index_kind"] for result in results] == ["symbol", "chunk"]


def test_multi_index_vector_retrieval_can_scale_kind_quotas_from_limit() -> None:
    store = FakeVectorStore()
    strategy = MultiIndexVectorRetrievalStrategy(
        FakeEmbeddingProvider(),
        store,
        {},
        {"chunk": 1.0, "symbol": 0.5},
    )

    strategy.search("where is auth?", limit=10)

    assert store.calls == [("chunk", 10), ("symbol", 5)]
