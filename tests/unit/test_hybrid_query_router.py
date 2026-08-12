from __future__ import annotations

import pytest

from code_diver.config import HybridSearchConfig
from code_diver.strategies.hybrid_query_router import HybridQueryRouter

pytestmark = pytest.mark.unit


def test_hybrid_query_router_uses_bm25_for_path_queries() -> None:
    config = HybridSearchConfig(routing_enabled=True)

    routed = HybridQueryRouter().route("where is docker-compose.dev.yml configured", ("docker", "compose"), config)

    assert HybridQueryRouter().route_name("where is docker-compose.dev.yml configured", ("docker", "compose")) == "path_symbol"
    assert routed.lexical_scoring == "bm25"
    assert routed.fusion == "weighted"
    assert routed.lexical_weight > config.lexical_weight
    assert routed.path_weight > config.path_weight


def test_hybrid_query_router_boosts_graph_for_workflow_queries() -> None:
    config = HybridSearchConfig(routing_enabled=True, graph_depth=1, graph_neighbor_limit=20)

    routed = HybridQueryRouter().route("where is command created and dispatched", ("command", "created"), config)

    assert HybridQueryRouter().route_name("where is command created and dispatched", ("command", "created")) == "workflow"
    assert routed.graph_weight > config.graph_weight
    assert routed.graph_depth == 2
    assert routed.graph_neighbor_limit == 30


def test_hybrid_query_router_keeps_semantic_queries_vector_first() -> None:
    config = HybridSearchConfig(routing_enabled=True, graph_weight=0.05, graph_depth=2, graph_neighbor_limit=30)

    routed = HybridQueryRouter().route("where is authorization handled", ("authorization",), config)

    assert HybridQueryRouter().route_name("where is authorization handled", ("authorization",)) == "semantic"
    assert routed.vector_weight == config.vector_weight
    assert routed.graph_weight == 0.01
    assert routed.graph_depth == 1
    assert routed.graph_neighbor_limit == 16
