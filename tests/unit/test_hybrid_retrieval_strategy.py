from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import HybridSearchConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore, GraphEdge
from code_diver.strategies import HybridRetrievalStrategy, RetrievalStrategy


pytestmark = pytest.mark.unit


class FakeRetrievalStrategy(RetrievalStrategy):
    def __init__(self, results: list[SearchResult]):
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results[:limit]


def test_hybrid_strategy_promotes_lexically_relevant_item(tmp_path: Path) -> None:
    auth_item = CodeItem(
        id="src/auth.py#1",
        path="src/auth.py",
        title="src/auth.py",
        content="def authorize_user():\n    validate authorization token and permissions",
    )
    cli_item = CodeItem(
        id="src/cli.py#1",
        path="src/cli.py",
        title="src/cli.py",
        content="def main():\n    parse arguments",
    )
    graph_store = _graph_store(tmp_path, [auth_item, cli_item], [])
    vector = FakeRetrievalStrategy([SearchResult(cli_item, 0.99)])
    strategy = HybridRetrievalStrategy(
        vector,
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.1,
            lexical_weight=0.6,
            path_weight=0.3,
            symbol_weight=0.0,
            graph_weight=0.0,
        ),
    )

    results = strategy.search("where is authorization handled?", limit=2)

    assert [result.item.path for result in results] == ["src/auth.py", "src/cli.py"]


def test_hybrid_strategy_adds_graph_neighbors(tmp_path: Path) -> None:
    command_item = CodeItem(
        id="src/commands.py#1",
        path="src/commands.py",
        title="create command",
        content="def create_command(): return StrategyCommand()",
    )
    strategy_item = CodeItem(
        id="src/strategies.py#1",
        path="src/strategies.py",
        title="strategy runner",
        content="class StrategyRunner: pass",
    )
    graph_store = _graph_store(
        tmp_path,
        [command_item, strategy_item],
        [GraphEdge(source=command_item.id, target=strategy_item.id, kind="calls", weight=0.9)],
    )
    vector = FakeRetrievalStrategy([SearchResult(command_item, 0.8)])
    strategy = HybridRetrievalStrategy(
        vector,
        graph_store,
        HybridSearchConfig(
            candidate_limit=5,
            lexical_candidate_limit=5,
            vector_weight=0.5,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.5,
            graph_depth=1,
            graph_neighbor_limit=5,
        ),
    )

    results = strategy.search("where is the strategy run?", limit=2)

    assert [result.item.path for result in results] == ["src/commands.py", "src/strategies.py"]


def _graph_store(tmp_path: Path, items: list[CodeItem], edges: list[GraphEdge]) -> CodeGraphStore:
    store = CodeGraphStore(tmp_path / "graph.json")
    store.save(CodeGraph(items={item.id: item for item in items}, edges=edges))
    return store
