from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from code_diver.config import GraphFileSearchConfig
from code_diver.domain import CodeItem, SearchResult
from code_diver.graph import CodeGraph, CodeGraphStore, GraphEdge
from code_diver.strategies import GraphFileRetrievalStrategy, RetrievalStrategy
from code_diver.strategies.hybrid_item_profile import HybridItemProfile
from code_diver.strategies.hybrid_item_profiler import HybridItemProfiler

pytestmark = pytest.mark.unit


class FakeRetrievalStrategy(RetrievalStrategy):
    def __init__(self, results: list[SearchResult]):
        self.results = results

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self.results[:limit]


class CountingHybridItemProfiler(HybridItemProfiler):
    def __init__(self) -> None:
        self.calls = 0

    def profile(self, item: CodeItem) -> HybridItemProfile:
        self.calls += 1
        return super().profile(item)


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


def test_graph_file_strategy_reuses_profile_cache_across_searches(tmp_path: Path) -> None:
    items = _build_catalog_items(24)
    store = _graph_store(tmp_path, items, [])
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(items[7], 0.9), SearchResult(items[3], 0.6)]),
        store,
        GraphFileSearchConfig(seed_limit=10, lexical_seed_limit=10),
    )
    profiler = CountingHybridItemProfiler()
    strategy.profiler = profiler

    first_results = strategy.search("module seven handler", limit=5)
    calls_after_first_search = profiler.calls
    assert calls_after_first_search > 0

    second_results = strategy.search("module seven handler", limit=5)

    assert profiler.calls == calls_after_first_search
    assert [(result.item.id, result.score) for result in second_results] == [
        (result.item.id, result.score) for result in first_results
    ]


def test_graph_file_strategy_concurrent_searches_match_sequential(tmp_path: Path) -> None:
    items = _build_catalog_items(30)
    store = _graph_store(tmp_path, items, [])
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(items[11], 0.9), SearchResult(items[3], 0.7)]),
        store,
        GraphFileSearchConfig(seed_limit=10, lexical_seed_limit=10),
    )
    query = "module eleven handler"
    expected = [(result.item.id, result.score) for result in strategy.search(query, limit=6)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(strategy.search, query, 6) for _ in range(8)]
        concurrent_results = [
            [(result.item.id, result.score) for result in future.result()] for future in futures
        ]

    for result in concurrent_results:
        assert result == expected


def _build_catalog_items(count: int) -> list[CodeItem]:
    return [
        CodeItem(
            id=f"module-{index}",
            path=f"src/module_{index}.py",
            title=f"src/module_{index}.py::file_manifest",
            content=f"file: src/module_{index}.py\nsymbols:\n- function handler_{index}",
            metadata={"index_kind": "file_manifest"},
        )
        for index in range(count)
    ]


def _graph_store(tmp_path: Path, items: list[CodeItem], edges: list[GraphEdge]) -> CodeGraphStore:
    store = CodeGraphStore(tmp_path / "graph.json")
    store.save(CodeGraph(items={item.id: item for item in items}, edges=edges))
    return store


def _hub_and_spokes(tmp_path: Path) -> tuple[CodeGraphStore, CodeItem]:
    """A hub whose five neighbours each own one private second-hop file.

    Descending edge weights make the level-1 ordering deterministic, so a level cap of two
    has exactly one observable consequence: only the top two spokes get to expand.
    """
    def item(name: str) -> CodeItem:
        return CodeItem(
            id=name,
            path=f"src/{name}.py",
            title=f"src/{name}.py::file_manifest",
            content=f"file: src/{name}.py\nsymbols:\n- function {name}",
            metadata={"index_kind": "file_manifest"},
        )

    hub = item("hub")
    spokes = [item(f"spoke{index}") for index in range(1, 6)]
    leaves = [item(f"leaf{index}") for index in range(1, 6)]
    edges = [
        GraphEdge(source=hub.id, target=spoke.id, kind="imports", weight=0.9 - 0.1 * index)
        for index, spoke in enumerate(spokes)
    ]
    edges += [
        GraphEdge(source=spoke.id, target=leaf.id, kind="imports", weight=0.9)
        for spoke, leaf in zip(spokes, leaves, strict=True)
    ]
    return _graph_store(tmp_path, [hub, *spokes, *leaves], edges), hub


def _propagated_leaves(tmp_path: Path, frontier_limit: int | None) -> set[str]:
    store, hub = _hub_and_spokes(tmp_path)
    strategy = GraphFileRetrievalStrategy(
        FakeRetrievalStrategy([SearchResult(hub, 1.0)]),
        store,
        GraphFileSearchConfig(
            seed_limit=10,
            lexical_seed_limit=0,
            vector_weight=1.0,
            lexical_weight=0.0,
            path_weight=0.0,
            symbol_weight=0.0,
            graph_weight=1.0,
            depth=2,
            neighbor_limit=10,
            frontier_limit=frontier_limit,
            decay=0.9,
        ),
    )
    results = strategy.search("hub", limit=20)
    return {result.item.id for result in results if result.item.id.startswith("leaf")}


def test_frontier_limit_caps_level_width_without_touching_per_node_fan_out(tmp_path: Path) -> None:
    # neighbor_limit=10 exceeds the hub's degree of 5, so per-node fan-out never binds here.
    assert _propagated_leaves(tmp_path, frontier_limit=2) == {"leaf1", "leaf2"}


def test_frontier_limit_defaults_to_neighbor_limit(tmp_path: Path) -> None:
    assert _propagated_leaves(tmp_path, frontier_limit=None) == {
        "leaf1",
        "leaf2",
        "leaf3",
        "leaf4",
        "leaf5",
    }
