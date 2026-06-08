from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import GraphFileSearchConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore, GraphEdge
from code_diver.strategies import GraphFileRetrievalStrategy, RetrievalStrategy


pytestmark = pytest.mark.unit


class FakeRetrievalStrategy(RetrievalStrategy):
    def __init__(self, results: list[SearchResult]):
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results[:limit]


def test_graph_file_strategy_promotes_connected_file(tmp_path: Path) -> None:
    api = CodeItem(
        id="api",
        path="src/api/users.py",
        title="src/api/users.py::file_manifest",
        content="file: src/api/users.py\nsymbols:\n- function update_user",
        metadata={"index_kind": "file_manifest"},
    )
    service = CodeItem(
        id="service",
        path="src/users/service.py",
        title="src/users/service.py::file_manifest",
        content="file: src/users/service.py\nsymbols:\n- class UserService\n- method UserService.update_user",
        metadata={"index_kind": "file_manifest"},
    )
    unrelated = CodeItem(
        id="unrelated",
        path="src/billing.py",
        title="src/billing.py::file_manifest",
        content="file: src/billing.py\nsymbols:\n- function charge_card",
        metadata={"index_kind": "file_manifest"},
    )
    store = _graph_store(
        tmp_path,
        [api, service, unrelated],
        [GraphEdge(source=api.id, target=service.id, kind="imports", weight=0.9)],
    )
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(api, 0.95), SearchResult(unrelated, 0.80)]),
        store,
        GraphFileSearchConfig(
            seed_limit=5,
            lexical_seed_limit=5,
            vector_weight=0.1,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=1.0,
            depth=1,
            neighbor_limit=5,
            decay=1.0,
        ),
    )

    results = strategy.search("where do we update user?", limit=3)

    assert [result.item.path for result in results[:2]] == ["src/users/service.py", "src/api/users.py"]


def test_graph_file_strategy_uses_lexical_seed_without_vector_hit(tmp_path: Path) -> None:
    target = CodeItem(
        id="target",
        path="src/auth/token.py",
        title="src/auth/token.py::file_manifest",
        content="file: src/auth/token.py\nsymbols:\n- function verify_token",
        metadata={"index_kind": "file_manifest"},
    )
    store = _graph_store(tmp_path, [target], [])
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy([]),
        store,
        GraphFileSearchConfig(
            seed_limit=5,
            lexical_seed_limit=5,
            vector_weight=0.0,
            lexical_weight=1.0,
            path_weight=1.0,
            symbol_weight=0.0,
            graph_weight=0.0,
        ),
    )

    results = strategy.search("auth token", limit=1)

    assert [result.item.path for result in results] == ["src/auth/token.py"]


def _graph_store(tmp_path: Path, items: list[CodeItem], edges: list[GraphEdge]) -> CodeGraphStore:
    store = CodeGraphStore(tmp_path / "graph.json")
    store.save(CodeGraph(items={item.id: item for item in items}, edges=edges))
    return store
