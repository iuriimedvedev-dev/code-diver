from __future__ import annotations

import pytest

from code_diver.domain import CodeItem
from code_diver.graph import CodeGraph, GraphEdge
from code_diver.settings import EdgeKind
from code_diver.strategies.file_graph_adjacency_index import FileGraphAdjacencyIndex
from code_diver.strategies.file_graph_candidate_expander import (
    FileGraphCandidateExpander,
)
from code_diver.strategies.graph_expansion_profile import GraphExpansionProfile


pytestmark = pytest.mark.unit


def test_file_graph_expander_projects_item_edges_to_file_representatives() -> None:
    seed_summary = CodeItem(
        id="seed-summary",
        path="src/api.py",
        title="src/api.py",
        content="api entrypoint",
        metadata={"index_kind": "file_summary"},
    )
    seed_symbol = CodeItem(
        id="seed-symbol",
        path="src/api.py",
        title="src/api.py::create_user",
        content="create user calls service",
        metadata={"index_kind": "symbol", "symbol": "create_user"},
    )
    target_summary = CodeItem(
        id="target-summary",
        path="src/service.py",
        title="src/service.py",
        content="user service",
        metadata={"index_kind": "file_summary"},
    )
    target_symbol = CodeItem(
        id="target-symbol",
        path="src/service.py",
        title="src/service.py::save_user",
        content="save user implementation",
        metadata={"index_kind": "symbol", "symbol": "save_user"},
    )
    graph = CodeGraph(
        items={
            item.id: item
            for item in [seed_summary, seed_symbol, target_summary, target_symbol]
        },
        edges=[
            GraphEdge(
                source=seed_symbol.id,
                target=target_symbol.id,
                kind=EdgeKind.CALLS.value,
                weight=0.9,
            )
        ],
    )
    profile = GraphExpansionProfile(
        depth=1, neighbor_limit=10, edge_weights={EdgeKind.CALLS.value: 1.0}
    )

    scores = FileGraphCandidateExpander(graph).expand({seed_summary.id: 1.0}, profile)

    assert scores == {"target-summary": 0.9}


def test_file_graph_expander_uses_precompiled_file_adjacency() -> None:
    seed_summary = CodeItem(
        id="seed-summary",
        path="src/api.py",
        title="src/api.py",
        content="api entrypoint",
        metadata={"index_kind": "file_summary"},
    )
    target_summary = CodeItem(
        id="target-summary",
        path="src/service.py",
        title="src/service.py",
        content="user service",
        metadata={"index_kind": "file_summary"},
    )
    adjacency = FileGraphAdjacencyIndex({"src/api.py": [("src/service.py", 0.8)]})
    profile = GraphExpansionProfile(
        depth=1, neighbor_limit=10, edge_weights={EdgeKind.CALLS.value: 1.0}
    )

    scores = FileGraphCandidateExpander(
        items=[seed_summary, target_summary],
        adjacency=adjacency,
    ).expand({seed_summary.id: 1.0}, profile)

    assert scores == {"target-summary": 0.8}


def test_file_graph_expander_projects_to_documentation_representatives() -> None:
    seed_summary = CodeItem(
        id="seed-summary",
        path="src/auth.py",
        title="src/auth.py",
        content="auth implementation",
        metadata={"index_kind": "file_summary"},
    )
    doc_chunk = CodeItem(
        id="doc-chunk",
        path="README.md",
        title="README.md:1-4::doc_chunk",
        content="Authentication setup",
        metadata={"index_kind": "doc_chunk"},
    )
    adjacency = FileGraphAdjacencyIndex({"src/auth.py": [("README.md", 0.7)]})
    profile = GraphExpansionProfile(
        depth=1, neighbor_limit=10, edge_weights={EdgeKind.REFERENCES.value: 1.0}
    )

    scores = FileGraphCandidateExpander(
        items=[seed_summary, doc_chunk],
        adjacency=adjacency,
    ).expand({seed_summary.id: 1.0}, profile)

    assert scores == {"doc-chunk": 0.7}
