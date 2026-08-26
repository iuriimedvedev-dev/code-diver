from __future__ import annotations

import pytest

from code_diver.config import GraphFileSearchConfig, HybridSearchConfig
from code_diver.strategies.query_fusion_router import QueryFusionRouter

pytestmark = pytest.mark.unit


def test_classifier_keeps_identifier_queries() -> None:
    router = QueryFusionRouter()
    assert router.classify("PsiElementVisitor") == "identifier"
    assert router.classify("com.intellij.openapi.vfs.VirtualFile") == "identifier"
    assert router.classify("docker-compose.dev.yml") == "identifier"
    assert router.classify("where is FileEditorManagerImpl") == "identifier"


def test_classifier_marks_prose_where_queries() -> None:
    router = QueryFusionRouter()
    assert router.classify("where is authorization handled") == "prose"
    assert router.classify("how does the editor save documents") == "prose"
    assert router.classify("find the code that opens a project") == "prose"


def test_prose_router_default_off() -> None:
    router = QueryFusionRouter()
    hybrid = HybridSearchConfig(path_weight=0.12, symbol_weight=0.10, vector_weight=0.42, lexical_weight=0.26)
    graph = GraphFileSearchConfig(path_weight=0.20, symbol_weight=0.10, vector_weight=0.25, lexical_weight=0.25)
    assert router.apply_hybrid("where is authorization handled", hybrid) is hybrid
    assert router.apply_graph_file("where is authorization handled", graph) is graph


def test_prose_router_downweights_path_and_symbol() -> None:
    router = QueryFusionRouter()
    hybrid = HybridSearchConfig(
        prose_fusion_router_enabled=True,
        path_weight=0.12,
        symbol_weight=0.10,
        vector_weight=0.42,
        lexical_weight=0.26,
        prose_path_weight=0.08,
        prose_symbol_weight=0.05,
    )
    graph = GraphFileSearchConfig(
        prose_fusion_router_enabled=True,
        path_weight=0.20,
        symbol_weight=0.10,
        vector_weight=0.25,
        lexical_weight=0.25,
        prose_path_weight=0.08,
        prose_symbol_weight=0.05,
    )
    routed_hybrid = router.apply_hybrid("where is authorization handled", hybrid)
    routed_graph = router.apply_graph_file("where is authorization handled", graph)
    assert routed_hybrid.path_weight == pytest.approx(0.08)
    assert routed_hybrid.symbol_weight == pytest.approx(0.05)
    assert routed_hybrid.vector_weight == pytest.approx(0.465)
    assert routed_hybrid.lexical_weight == pytest.approx(0.305)
    assert routed_graph.path_weight == pytest.approx(0.08)
    assert routed_graph.symbol_weight == pytest.approx(0.05)
    assert routed_graph.vector_weight == pytest.approx(0.335)
    assert routed_graph.lexical_weight == pytest.approx(0.335)


def test_identifier_query_keeps_h52_weights_when_enabled() -> None:
    router = QueryFusionRouter()
    graph = GraphFileSearchConfig(
        prose_fusion_router_enabled=True,
        path_weight=0.20,
        symbol_weight=0.10,
        vector_weight=0.25,
        lexical_weight=0.25,
    )
    routed = router.apply_graph_file("PsiManager.getInstance", graph)
    assert routed.path_weight == 0.20
    assert routed.symbol_weight == 0.10
    assert routed.vector_weight == 0.25
