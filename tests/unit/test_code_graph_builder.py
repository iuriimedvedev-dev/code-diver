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


def test_code_graph_builder_creates_symbol_reference_edges(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("def register():\n    save_user()\n", encoding="utf-8")
    (tmp_path / "repository.py").write_text("def save_user(): pass\n", encoding="utf-8")
    items = [
        CodeItem("service", "service.py", "service.py::register", "def register():\n    save_user()"),
        CodeItem(
            "repository",
            "repository.py",
            "repository.py::save_user",
            "def save_user(): pass",
            metadata={"symbol": "save_user"},
        ),
    ]

    graph = CodeGraphBuilder().build(tmp_path, items)

    assert any(
        edge.source == "service" and edge.target == "repository" and edge.kind == EdgeKind.REFERENCES.value
        for edge in graph.edges
    )


def test_code_graph_builder_creates_ast_contains_and_call_edges(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        """
class Service:
    def run(self):
        save_user()

def save_user():
    return "saved"
""".strip(),
        encoding="utf-8",
    )
    items = [
        CodeItem("file", "service.py", "service.py", "class Service:\n    def run(self):\n        save_user()"),
        CodeItem("class", "service.py", "service.py::Service", "class Service:", metadata={"symbol": "Service"}),
        CodeItem(
            "method",
            "service.py",
            "service.py::Service.run",
            "def run(self):\n    save_user()",
            metadata={"symbol": "Service.run"},
        ),
        CodeItem(
            "function",
            "service.py",
            "service.py::save_user",
            "def save_user():\n    return 'saved'",
            metadata={"symbol": "save_user"},
        ),
    ]
    for item in items:
        item.start_line = 1 if item.id in {"file", "class"} else 2 if item.id == "method" else 5
        item.end_line = 6 if item.id == "file" else 3 if item.id in {"class", "method"} else 6

    graph = CodeGraphBuilder().build(tmp_path, items)

    assert any(
        edge.source == "file" and edge.target == "class" and edge.kind == EdgeKind.CONTAINS.value
        for edge in graph.edges
    )
    assert any(
        edge.source == "class" and edge.target == "method" and edge.kind == EdgeKind.CONTAINS.value
        for edge in graph.edges
    )
    assert any(
        edge.source == "method" and edge.target == "function" and edge.kind == EdgeKind.CALLS.value
        for edge in graph.edges
    )
