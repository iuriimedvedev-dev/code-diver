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


def test_code_symbol_extractor_handles_python() -> None:
    text = """
class MyService:
    def process(self):
        pass

def top_func():
    pass
""".strip()
    symbols = CodeSymbolExtractor().extract("src/service.py", text)
    assert [(s.kind, s.name) for s in symbols] == [
        ("class", "MyService"),
        ("method", "MyService.process"),
        ("function", "top_func"),
    ]


def test_code_symbol_extractor_handles_rust() -> None:
    text = """
pub struct Pipeline {
    pub id: u64,
}

pub fn run_pipeline() {}
""".strip()
    symbols = CodeSymbolExtractor().extract("src/pipeline.rs", text)
    assert ("struct", "Pipeline") in [(s.kind, s.name) for s in symbols]
    assert ("function", "run_pipeline") in [(s.kind, s.name) for s in symbols]


def test_code_symbol_extractor_handles_go() -> None:
    text = """
package main

type Config struct {
    Port int
}

func NewConfig() *Config {
    return &Config{}
}
""".strip()
    symbols = CodeSymbolExtractor().extract("main.go", text)
    assert ("struct", "Config") in [(s.kind, s.name) for s in symbols]
    assert ("function", "NewConfig") in [(s.kind, s.name) for s in symbols]


def test_code_symbol_extractor_handles_cpp() -> None:
    text = """
namespace core {
class Engine {
public:
    void start();
};
}
""".strip()
    symbols = CodeSymbolExtractor().extract("src/engine.cpp", text)
    assert ("class", "Engine") in [(s.kind, s.name) for s in symbols]


def test_code_symbol_extractor_handles_ts_js() -> None:
    text = """
export interface User {
    id: string;
}

export class UserService {
}

export function makeUser(): User {}
""".strip()
    symbols = CodeSymbolExtractor().extract("src/user.ts", text)
    names = [(s.kind, s.name) for s in symbols]
    assert ("interface", "User") in names
    assert ("class", "UserService") in names
    assert ("function", "makeUser") in names


def test_code_symbol_extractor_handles_generic_markdown() -> None:
    text = """
# API Documentation

## Endpoints
""".strip()
    symbols = CodeSymbolExtractor().extract("docs/api.md", text)
    assert [(s.kind, s.name) for s in symbols] == [
        ("title", "API Documentation"),
        ("section", "Endpoints"),
    ]

