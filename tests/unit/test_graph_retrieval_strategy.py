from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore, GraphEdge
from code_diver.settings import EdgeKind
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


def test_graph_strategy_uses_query_aware_workflow_traversal(tmp_path: Path) -> None:
    seed = CodeItem(id="src/commands.py#1", path="src/commands.py", title="command", content="create command")
    handler = CodeItem(id="src/handlers.py#1", path="src/handlers.py", title="handler", content="dispatch command")
    service = CodeItem(id="src/service.py#1", path="src/service.py", title="service", content="run workflow")
    graph_store = CodeGraphStore(tmp_path / "graph.json")
    graph_store.save(
        CodeGraph(
            items={item.id: item for item in [seed, handler, service]},
            edges=[
                GraphEdge(source=seed.id, target=handler.id, kind=EdgeKind.CALLS.value, weight=0.9),
                GraphEdge(source=handler.id, target=service.id, kind=EdgeKind.CALLS.value, weight=0.9),
            ],
        )
    )
    strategy = GraphRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(seed, 0.9)]),
        graph_store,
        expansion_depth=2,
        neighbor_limit=10,
    )

    results = strategy.search("where is command created and dispatched", limit=3)

    assert [result.item.path for result in results] == ["src/commands.py", "src/handlers.py", "src/service.py"]
