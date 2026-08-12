from __future__ import annotations

import pytest

from code_diver.services import CodeSymbolExtractor

pytestmark = pytest.mark.unit


def test_code_symbol_extractor_handles_java_modifiers() -> None:
    text = """
package com.intellij.example;

public final class SearchManager {
  private static Result findTarget(Project project, String query) {
    return null;
  }

  protected void refreshIndex() {
  }
}
""".strip()

    symbols = CodeSymbolExtractor().extract("platform/example/SearchManager.java", text)

    assert [(symbol.kind, symbol.name) for symbol in symbols] == [
        ("class", "SearchManager"),
        ("method", "findTarget"),
        ("method", "refreshIndex"),
    ]


def test_code_symbol_extractor_handles_kotlin_declarations() -> None:
    text = """
internal object WorkspaceModelIndex {
  suspend fun rebuildProjectIndex(project: Project) {
  }
}

sealed class SearchCommand

private fun parseCommandLine(text: String): SearchCommand {
  TODO()
}
""".strip()

    symbols = CodeSymbolExtractor().extract("platform/example/WorkspaceModelIndex.kt", text)

    assert [(symbol.kind, symbol.name) for symbol in symbols] == [
        ("object", "WorkspaceModelIndex"),
        ("function", "rebuildProjectIndex"),
        ("class", "SearchCommand"),
        ("function", "parseCommandLine"),
    ]
