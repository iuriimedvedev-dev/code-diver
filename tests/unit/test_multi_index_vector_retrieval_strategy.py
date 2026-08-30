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


class FakeChunkVectorStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query_vector: list[float], limit: int) -> list[SearchResult]:
        return []

    def search_by_index_kind(self, query_vector: list[float], limit: int, index_kind: str) -> list[SearchResult]:
        self.calls.append((index_kind, limit))
        points = [("src/big.py", 0.9), ("src/big.py", 0.8), ("src/other.py", 0.7), ("src/third.py", 0.6)]
        return [
            SearchResult(
                item=CodeItem(
                    id=f"{path}::{index_kind}::{index}",
                    path=path,
                    title=path,
                    content=path,
                    metadata={"index_kind": index_kind},
                ),
                score=score,
            )
            for index, (path, score) in enumerate(points)
        ][:limit]


def test_multi_index_vector_retrieval_keeps_every_point_without_path_dedup() -> None:
    store = FakeChunkVectorStore()
    strategy = MultiIndexVectorRetrievalStrategy(FakeEmbeddingProvider(), store, {"symbol_chunk": 2})

    results = strategy.search("where is auth?", limit=10)

    assert store.calls == [("symbol_chunk", 2)]
    assert [result.item.path for result in results] == ["src/big.py", "src/big.py"]


def test_multi_index_vector_retrieval_path_dedup_spends_lane_budget_on_distinct_files() -> None:
    store = FakeChunkVectorStore()
    strategy = MultiIndexVectorRetrievalStrategy(
        FakeEmbeddingProvider(),
        store,
        {"symbol_chunk": 2},
        path_dedup_kinds=["symbol_chunk"],
    )

    results = strategy.search("where is auth?", limit=10)

    assert store.calls == [("symbol_chunk", 8)]
    assert [result.item.path for result in results] == ["src/big.py", "src/other.py"]
    assert [result.score for result in results] == [0.9, 0.7]


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
