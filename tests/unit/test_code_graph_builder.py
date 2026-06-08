from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.graph import CodeGraphBuilder
from code_diver.settings import EdgeKind
from code_diver.graph.code_graph_builder import REFERENCE_EDGES_PER_SOURCE


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


def test_code_graph_builder_tolerates_non_utf8_source_for_import_edges(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_bytes(b"import repository\nbad = '\x92'\n")
    (tmp_path / "repository.py").write_text("def save(): pass\n", encoding="utf-8")
    items = [
        CodeItem("service", "service.py", "service", "import repository"),
        CodeItem("repository", "repository.py", "repository", "def save(): pass"),
    ]

    graph = CodeGraphBuilder().build(tmp_path, items)

    assert any(edge.source == "service" and edge.target == "repository" for edge in graph.edges)


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


def test_code_graph_builder_links_file_summary_to_file_items(tmp_path: Path) -> None:
    items = [
        CodeItem(
            "summary",
            "service.py",
            "service.py::file_summary",
            "symbols:\n- function run",
            metadata={"index_kind": "file_summary"},
        ),
        CodeItem("chunk", "service.py", "service.py", "def run(): pass", start_line=1, end_line=1),
        CodeItem(
            "symbol",
            "service.py",
            "service.py::run",
            "def run(): pass",
            start_line=1,
            end_line=1,
            metadata={"index_kind": "symbol", "symbol": "run"},
        ),
    ]

    graph = CodeGraphBuilder(ast_enabled=False).build(tmp_path, items)

    assert any(
        edge.source == "summary" and edge.target == "chunk" and edge.kind == EdgeKind.SUMMARIZES.value
        for edge in graph.edges
    )
    assert any(
        edge.source == "summary" and edge.target == "symbol" and edge.kind == EdgeKind.SUMMARIZES.value
        for edge in graph.edges
    )


def test_code_graph_builder_does_not_treat_file_metadata_kinds_as_symbols(tmp_path: Path) -> None:
    source = CodeItem(
        "source",
        "source.py",
        "source.py::file_summary",
        "file: source.py\nsymbols:\n- function run",
        metadata={"index_kind": "file_summary"},
    )
    target = CodeItem(
        "target",
        "target.py",
        "target.py::file_summary",
        "file: target.py\nsymbols:\n- function save",
        metadata={"index_kind": "file_summary"},
    )

    graph = CodeGraphBuilder(ast_enabled=False).build(tmp_path, [source, target])

    assert not any(edge.kind == EdgeKind.REFERENCES.value for edge in graph.edges)


def test_code_graph_builder_limits_reference_edges_per_source(tmp_path: Path) -> None:
    source = CodeItem(
        "source",
        "source.py",
        "source",
        "\n".join(f"symbol_{index}()" for index in range(20)),
    )
    targets = [
        CodeItem(
            f"target-{index}",
            f"target_{index}.py",
            f"target_{index}.py::symbol_{index}",
            f"def symbol_{index}(): pass",
            metadata={"symbol": f"symbol_{index}"},
        )
        for index in range(20)
    ]

    graph = CodeGraphBuilder(ast_enabled=False).build(tmp_path, [source, *targets])

    reference_edges = [
        edge for edge in graph.edges if edge.source == source.id and edge.kind == EdgeKind.REFERENCES.value
    ]
    assert len(reference_edges) == REFERENCE_EDGES_PER_SOURCE


def test_code_graph_builder_can_disable_reference_edges(tmp_path: Path) -> None:
    source = CodeItem("source", "source.py", "source", "save_user()")
    target = CodeItem(
        "target",
        "repository.py",
        "repository.py::save_user",
        "def save_user(): pass",
        metadata={"symbol": "save_user"},
    )

    graph = CodeGraphBuilder(ast_enabled=False, reference_edges_enabled=False).build(tmp_path, [source, target])

    assert not any(edge.kind == EdgeKind.REFERENCES.value for edge in graph.edges)


def test_code_graph_builder_can_disable_call_edges(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        "def run():\n    save_user()\n\ndef save_user():\n    return None\n",
        encoding="utf-8",
    )
    items = [
        CodeItem("run", "service.py", "service.py::run", "def run():\n    save_user()", metadata={"symbol": "run"}),
        CodeItem(
            "save",
            "service.py",
            "service.py::save_user",
            "def save_user():\n    return None",
            metadata={"symbol": "save_user"},
        ),
    ]

    graph = CodeGraphBuilder(ast_enabled=True, call_edges_enabled=False).build(tmp_path, items)

    assert not any(edge.kind == EdgeKind.CALLS.value for edge in graph.edges)
