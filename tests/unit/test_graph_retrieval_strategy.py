from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore
from code_diver.strategies import GraphRetrievalStrategy, RetrievalStrategy


pytestmark = pytest.mark.unit


class FakeRetrievalStrategy(RetrievalStrategy):
    def __init__(self, results: list[SearchResult]):
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results[:limit]


def test_graph_strategy_keeps_vector_seeds_when_graph_is_stale(tmp_path: Path) -> None:
    seed = CodeItem(id="src/current.py#1", path="src/current.py", title="current", content="current index item")
    stale = CodeItem(id="src/stale.py#1", path="src/stale.py", title="stale", content="stale graph item")
    graph_store = CodeGraphStore(tmp_path / "graph.json")
    graph_store.save(CodeGraph(items={stale.id: stale}, edges=[]))
    strategy = GraphRetrievalStrategy(FakeRetrievalStrategy([SearchResult(seed, 0.8)]), graph_store)

    results = strategy.search("current", limit=10)

    assert [result.item.id for result in results] == [seed.id]
