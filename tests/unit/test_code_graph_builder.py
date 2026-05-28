from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.graph import CodeGraphBuilder
from code_diver.settings import EdgeKind


pytestmark = pytest.mark.unit


def test_code_graph_builder_creates_python_import_edges(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("import repository\n", encoding="utf-8")
    (tmp_path / "repository.py").write_text("def save(): pass\n", encoding="utf-8")
    items = [
        CodeItem("service", "service.py", "service", "import repository"),
        CodeItem("repository", "repository.py", "repository", "def save(): pass"),
    ]

    graph = CodeGraphBuilder().build(tmp_path, items)

    assert any(
        edge.source == "service" and edge.target == "repository" and edge.kind == EdgeKind.IMPORTS.value
        for edge in graph.edges
    )
