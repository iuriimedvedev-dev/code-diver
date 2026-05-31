from __future__ import annotations

import pytest

from code_diver.domain import CodeItem
from code_diver.graph import CodeGraph, GraphEdge
from code_diver.settings import EdgeKind
from code_diver.strategies.graph_candidate_expander import GraphCandidateExpander
from code_diver.strategies.graph_expansion_profile_factory import GraphExpansionProfileFactory
from code_diver.strategies.graph_neighbor_index import GraphNeighborIndex


pytestmark = pytest.mark.unit


def test_graph_expander_uses_workflow_call_edges_across_two_hops() -> None:
    seed = CodeItem("cli", "cli.py", "cli", "create command")
    handler = CodeItem("handler", "handler.py", "handler", "handle command")
    service = CodeItem("service", "service.py", "service", "run workflow")
    graph = CodeGraph(
        items={item.id: item for item in [seed, handler, service]},
        edges=[
            GraphEdge(source=seed.id, target=handler.id, kind=EdgeKind.CALLS.value, weight=0.9),
            GraphEdge(source=handler.id, target=service.id, kind=EdgeKind.CALLS.value, weight=0.9),
        ],
    )
    profile = GraphExpansionProfileFactory().create("workflow", depth=2, neighbor_limit=10)

    scores = GraphCandidateExpander(GraphNeighborIndex(graph)).expand({seed.id: 1.0}, profile)

    assert scores[handler.id] > scores[service.id] > 0


def test_graph_expander_ignores_unhelpful_edge_types_for_semantic_profile() -> None:
    seed = CodeItem("seed", "seed.py", "seed", "seed")
    target = CodeItem("target", "target.py", "target", "target")
    graph = CodeGraph(
        items={item.id: item for item in [seed, target]},
        edges=[GraphEdge(source=seed.id, target=target.id, kind="unknown_edge", weight=1.0)],
    )
    profile = GraphExpansionProfileFactory().create("semantic", depth=1, neighbor_limit=10)

    scores = GraphCandidateExpander(GraphNeighborIndex(graph)).expand({seed.id: 1.0}, profile)

    assert scores == {}
