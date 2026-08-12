from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.domain import CodeItem
from code_diver.graph import CodeGraphBuilder
from code_diver.graph.code_graph_builder import REFERENCE_EDGES_PER_SOURCE
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


def test_code_graph_builder_links_documentation_chunks_to_summary(tmp_path: Path) -> None:
    items = [
        CodeItem(
            "doc-summary",
            "README.md",
            "README.md::doc_summary",
            "compact_summary:\n- Authentication lives in src/auth.py",
            metadata={"index_kind": "doc_summary"},
        ),
        CodeItem(
            "doc-manifest",
            "README.md",
            "README.md::doc_manifest",
            "links:\n- auth -> src/auth.py",
            metadata={"index_kind": "doc_manifest"},
        ),
        CodeItem(
            "doc-chunk",
            "README.md",
            "README.md:1-4::doc_chunk",
            "See [auth](src/auth.py).",
            start_line=1,
            end_line=4,
            metadata={"index_kind": "doc_chunk"},
        ),
    ]

    graph = CodeGraphBuilder(ast_enabled=False).build(tmp_path, items)

    assert any(
        edge.source == "doc-summary" and edge.target == "doc-chunk" and edge.kind == EdgeKind.SUMMARIZES.value
        for edge in graph.edges
    )
    assert any(
        edge.source == "doc-manifest" and edge.target == "doc-chunk" and edge.kind == EdgeKind.SUMMARIZES.value
        for edge in graph.edges
    )


def test_code_graph_builder_links_documentation_path_references_to_code_file(tmp_path: Path) -> None:
    items = [
        CodeItem(
            "doc-chunk",
            "README.md",
            "README.md:1-4::doc_chunk",
            "Authentication implementation is in [auth](src/auth.py) and `src/users.py`.",
            start_line=1,
            end_line=4,
            metadata={"index_kind": "doc_chunk"},
        ),
        CodeItem(
            "doc-manifest",
            "README.md",
            "README.md::doc_manifest",
            "links:\n- auth -> src/auth.py",
            metadata={"index_kind": "doc_manifest"},
        ),
        CodeItem(
            "auth-summary",
            "src/auth.py",
            "src/auth.py::file_summary",
            "file: src/auth.py\nsymbols:\n- function authenticate",
            metadata={"index_kind": "file_summary"},
        ),
        CodeItem(
            "users-summary",
            "src/users.py",
            "src/users.py::file_summary",
            "file: src/users.py\nsymbols:\n- function create_user",
            metadata={"index_kind": "file_summary"},
        ),
    ]

    graph = CodeGraphBuilder(ast_enabled=False).build(tmp_path, items)

    referenced = {
        edge.target
        for edge in graph.edges
        if edge.source == "doc-chunk" and edge.kind == EdgeKind.REFERENCES.value
    }
    assert referenced == {"auth-summary", "users-summary"}
    assert any(
        edge.source == "doc-manifest"
        and edge.target == "auth-summary"
        and edge.kind == EdgeKind.REFERENCES.value
        for edge in graph.edges
    )


def _jvm_repo(tmp_path: Path) -> list[CodeItem]:
    """A two-module JVM layout: the package root is buried under a source root."""
    util = tmp_path / "platform/util/src/com/intellij/util"
    api = tmp_path / "platform/core-api/src/com/intellij/openapi/project"
    util.mkdir(parents=True)
    api.mkdir(parents=True)
    (util / "ArrayUtil.java").write_text("package com.intellij.util;\nclass ArrayUtil {}\n", encoding="utf-8")
    (api / "Project.kt").write_text("package com.intellij.openapi.project\nclass Project\n", encoding="utf-8")
    consumer = tmp_path / "platform/lang-impl/src/com/intellij/lang"
    consumer.mkdir(parents=True)
    (consumer / "Consumer.java").write_text(
        "package com.intellij.lang;\n\n"
        "import com.intellij.util.ArrayUtil;\n"
        "import com.intellij.openapi.project.Project;\n"
        "import java.util.List;\n"
        "import com.intellij.util.*;\n\n"
        "class Consumer {}\n",
        encoding="utf-8",
    )
    return [
        CodeItem("util", "platform/util/src/com/intellij/util/ArrayUtil.java", "ArrayUtil", "x"),
        CodeItem("project", "platform/core-api/src/com/intellij/openapi/project/Project.kt", "Project", "x"),
        CodeItem("consumer", "platform/lang-impl/src/com/intellij/lang/Consumer.java", "Consumer", "x"),
    ]


def test_code_graph_builder_creates_jvm_import_edges_across_source_roots(tmp_path: Path) -> None:
    # Before this existed the builder returned an empty set for every .java/.kt file, so a
    # 75k-file JVM monorepo produced a graph with zero cross-file edges -- and nothing failed,
    # it just silently had no graph to search over.
    items = _jvm_repo(tmp_path)

    graph = CodeGraphBuilder().build(tmp_path, items)
    imports = {(e.source, e.target) for e in graph.edges if e.kind == EdgeKind.IMPORTS.value}

    assert ("consumer", "util") in imports
    assert ("consumer", "project") in imports


def test_code_graph_builder_ignores_jvm_imports_outside_the_repository(tmp_path: Path) -> None:
    items = _jvm_repo(tmp_path)

    graph = CodeGraphBuilder().build(tmp_path, items)
    targets = {e.target for e in graph.edges if e.kind == EdgeKind.IMPORTS.value and e.source == "consumer"}

    # `java.util.List` resolves to nothing in-repo, and the wildcard `com.intellij.util.*`
    # names no class, so neither may invent an edge.
    assert targets == {"util", "project"}


def test_code_graph_builder_resolves_static_and_nested_jvm_imports(tmp_path: Path) -> None:
    util = tmp_path / "platform/util/src/com/intellij/util"
    util.mkdir(parents=True)
    (util / "StringUtil.java").write_text("package com.intellij.util;\nclass StringUtil {}\n", encoding="utf-8")
    consumer = tmp_path / "src/com/intellij/lang"
    consumer.mkdir(parents=True)
    (consumer / "Consumer.java").write_text(
        "import static com.intellij.util.StringUtil.isEmpty;\n"
        "import com.intellij.util.StringUtil.Inner;\n",
        encoding="utf-8",
    )
    items = [
        CodeItem("util", "platform/util/src/com/intellij/util/StringUtil.java", "StringUtil", "x"),
        CodeItem("consumer", "src/com/intellij/lang/Consumer.java", "Consumer", "x"),
    ]

    graph = CodeGraphBuilder().build(tmp_path, items)

    # Both the static member and the nested class fall back to the enclosing top-level file.
    assert any(e.source == "consumer" and e.target == "util" for e in graph.edges)


def test_code_graph_builder_does_not_match_a_same_named_class_in_another_package(tmp_path: Path) -> None:
    right = tmp_path / "a/src/com/intellij/util"
    wrong = tmp_path / "b/src/org/other/util"
    right.mkdir(parents=True)
    wrong.mkdir(parents=True)
    (right / "Ref.java").write_text("package com.intellij.util;\n", encoding="utf-8")
    (wrong / "Ref.java").write_text("package org.other.util;\n", encoding="utf-8")
    consumer = tmp_path / "c/src/com/x"
    consumer.mkdir(parents=True)
    (consumer / "Consumer.java").write_text("import com.intellij.util.Ref;\n", encoding="utf-8")
    items = [
        CodeItem("right", "a/src/com/intellij/util/Ref.java", "Ref", "x"),
        CodeItem("wrong", "b/src/org/other/util/Ref.java", "Ref", "x"),
        CodeItem("consumer", "c/src/com/x/Consumer.java", "Consumer", "x"),
    ]

    graph = CodeGraphBuilder().build(tmp_path, items)
    targets = {e.target for e in graph.edges if e.kind == EdgeKind.IMPORTS.value and e.source == "consumer"}

    assert targets == {"right"}
