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


def test_graph_file_strategy_prefers_file_summary_as_rerank_evidence(tmp_path: Path) -> None:
    summary = CodeItem(
        id="summary",
        path="src/users/service.py",
        title="src/users/service.py::file_summary",
        content="file: src/users/service.py\nhead:\n- def update_user():\n-     validate_user()",
        metadata={"index_kind": "file_summary"},
    )
    manifest = CodeItem(
        id="manifest",
        path="src/users/service.py",
        title="src/users/service.py::file_manifest",
        content="file: src/users/service.py\nsymbols:\n- function update_user",
        metadata={"index_kind": "file_manifest"},
    )
    store = _graph_store(tmp_path, [summary, manifest], [])
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(manifest, 0.9)]),
        store,
        GraphFileSearchConfig(seed_limit=5, lexical_seed_limit=5),
    )

    results = strategy.search("where do we update user?", limit=1)

    assert results[0].item.id == "summary"


def test_graph_file_strategy_keeps_best_base_score_when_file_has_duplicate_items(tmp_path: Path) -> None:
    target_summary = CodeItem(
        id="target-summary",
        path="src/target.py",
        title="src/target.py::file_summary",
        content="file: src/target.py\nhead:\n- def target(): pass",
        metadata={"index_kind": "file_summary"},
    )
    target_manifest = CodeItem(
        id="target-manifest",
        path="src/target.py",
        title="src/target.py::file_manifest",
        content="file: src/target.py\nsymbols:\n- function target",
        metadata={"index_kind": "file_manifest"},
    )
    other = CodeItem(
        id="other",
        path="src/other.py",
        title="src/other.py::file_summary",
        content="file: src/other.py",
        metadata={"index_kind": "file_summary"},
    )
    store = _graph_store(tmp_path, [target_summary, target_manifest, other], [])
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy(
            [
                SearchResult(target_summary, 0.9),
                SearchResult(other, 0.8),
                SearchResult(target_manifest, 0.1),
            ]
        ),
        store,
        GraphFileSearchConfig(
            seed_limit=5,
            lexical_seed_limit=0,
            vector_weight=1.0,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=0.0,
        ),
    )

    results = strategy.search("target", limit=2)

    assert [result.item.path for result in results] == ["src/target.py", "src/other.py"]


def test_graph_file_strategy_can_promote_documentation_representatives(tmp_path: Path) -> None:
    code = CodeItem(
        id="code-summary",
        path="src/auth.py",
        title="src/auth.py::file_summary",
        content="file: src/auth.py\nsymbols:\n- function authenticate",
        metadata={"index_kind": "file_summary"},
    )
    doc = CodeItem(
        id="doc-summary",
        path="README.md",
        title="README.md::doc_summary",
        content="doc: README.md\ncompact_summary:\n- Authentication setup references src/auth.py",
        metadata={"index_kind": "doc_summary"},
    )
    store = _graph_store(
        tmp_path,
        [code, doc],
        [GraphEdge(source=code.id, target=doc.id, kind="references", weight=0.9)],
    )
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(code, 0.9)]),
        store,
        GraphFileSearchConfig(
            seed_limit=5,
            lexical_seed_limit=0,
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

    results = strategy.search("how is authentication configured?", limit=2)

    assert [result.item.id for result in results] == ["doc-summary", "code-summary"]


def _graph_store(tmp_path: Path, items: list[CodeItem], edges: list[GraphEdge]) -> CodeGraphStore:
    store = CodeGraphStore(tmp_path / "graph.json")
    store.save(CodeGraph(items={item.id: item for item in items}, edges=edges))
    return store
