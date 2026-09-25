from __future__ import annotations

import pytest

from code_diver.indexing import (
    CppStrategy,
    GenericStrategy,
    GoStrategy,
    JvmStrategy,
    LanguageEvidence,
    LanguageIndexingRouter,
    LanguageStrategy,
    PythonStrategy,
    RustStrategy,
    StructuralSpan,
    TsJsStrategy,
    get_language_router,
)

pytestmark = pytest.mark.unit


def test_language_strategy_protocol_conformance() -> None:
    router = get_language_router()
    for _ext, strategy in router.registry.items():
        assert isinstance(strategy, LanguageStrategy)
        assert strategy.name
        assert strategy.supported_extensions
    assert isinstance(router.fallback, LanguageStrategy)
    # Check StructuralSpan and LanguageEvidence types directly
    span = StructuralSpan(title="test", kind="custom", start_line=1, end_line=10)
    assert span.title == "test"
    evidence = LanguageEvidence(package="pkg", imports=["a"], exports=["b"])
    assert evidence.package == "pkg"
    assert evidence.namespace == "pkg"
    custom_router = LanguageIndexingRouter()
    assert custom_router.fallback.name == "generic"


def test_python_strategy_ast_extraction() -> None:
    code = '''"""Module docstring."""
import os
from math import sqrt

__all__ = ["MyClass", "helper"]

@decorator
class MyClass:
    """Class docstring."""
    @property
    def value(self) -> int:
        return 42

    def compute(self, x: int) -> int:
        return x * 2

async def async_fetch():
    pass

def helper():
    pass
'''
    strategy = PythonStrategy()
    symbols = strategy.extract_symbols("src/example.py", code)
    symbol_names = [(s.kind, s.name) for s in symbols]

    assert ("class", "MyClass") in symbol_names
    assert ("method", "MyClass.value") in symbol_names
    assert ("method", "MyClass.compute") in symbol_names
    assert ("function", "async_fetch") in symbol_names
    assert ("function", "helper") in symbol_names

    # Check decorator captured
    my_class_sym = next(s for s in symbols if s.name == "MyClass")
    assert "@decorator" in my_class_sym.signature
    value_sym = next(s for s in symbols if s.name == "MyClass.value")
    assert "@property" in value_sym.signature

    # Spans
    spans = strategy.extract_spans("src/example.py", code, len(code.splitlines()))
    assert any(span.kind == "preamble" for span in spans)
    assert any(span.title == "MyClass" for span in spans)
    assert any(span.title == "async_fetch" for span in spans)

    # Evidence
    evidence = strategy.extract_evidence("src/example.py", code)
    assert "os" in evidence.imports
    assert "math.sqrt" in evidence.imports
    assert evidence.exports == ["MyClass", "helper"]
    assert "class MyClass" in evidence.declarations
    assert "async def async_fetch" in evidence.declarations
    assert any("Module docstring" in h for h in evidence.doc_hints)
    assert evidence.companion_path == "tests/test_example.py"


def test_jvm_strategy_java_and_kotlin() -> None:
    java_code = """package com.diver.test;

import java.util.List;
import static java.util.Collections.emptyList;

/**
 * Service for users.
 */
public class UserService {
    public UserService() {
    }

    public List<String> listUsers() {
        return emptyList();
    }
}

public record UserDto(String id, String name) {}
"""
    strategy = JvmStrategy()
    java_symbols = strategy.extract_symbols("UserService.java", java_code)
    kinds_and_names = [(s.kind, s.name) for s in java_symbols]
    assert ("class", "UserService") in kinds_and_names
    assert ("method", "UserService") in kinds_and_names
    assert ("method", "listUsers") in kinds_and_names
    assert ("record", "UserDto") in kinds_and_names

    java_evidence = strategy.extract_evidence("UserService.java", java_code)
    assert java_evidence.package == "com.diver.test"
    assert "java.util.List" in java_evidence.imports
    assert "UserService" in java_evidence.exports
    assert any("Service for users" in h for h in java_evidence.doc_hints)
    assert java_evidence.companion_path == "UserServiceTest.java"

    kotlin_code = """package com.diver.kt

import kotlinx.coroutines.flow.Flow

sealed class UiState

object EmptyState : UiState()

suspend fun fetchState(): UiState {
    return EmptyState
}
"""
    kt_symbols = strategy.extract_symbols("State.kt", kotlin_code)
    kt_names = [(s.kind, s.name) for s in kt_symbols]
    assert ("class", "UiState") in kt_names
    assert ("object", "EmptyState") in kt_names
    assert ("function", "fetchState") in kt_names

    kt_evidence = strategy.extract_evidence("State.kt", kotlin_code)
    assert kt_evidence.package == "com.diver.kt"
    assert "fetchState" in kt_evidence.exports
    assert kt_evidence.companion_path == "StateTest.kt"


def test_rust_strategy_extraction() -> None:
    rust_code = """//! Crate documentation.
use std::collections::HashMap;

pub struct Config {
    pub timeout: u64,
}

pub enum Status {
    Active,
    Inactive,
}

pub trait Runner {
    fn run(&self);
}

impl Runner for Config {
    fn run(&self) {}
}

pub async fn execute(cfg: &Config) {
    cfg.run();
}

macro_rules! my_macro {
    () => {};
}
"""
    strategy = RustStrategy()
    symbols = strategy.extract_symbols("src/config.rs", rust_code)
    kinds_and_names = [(s.kind, s.name) for s in symbols]

    assert ("struct", "Config") in kinds_and_names
    assert ("enum", "Status") in kinds_and_names
    assert ("trait", "Runner") in kinds_and_names
    assert ("impl", "Runner for Config") in kinds_and_names
    assert ("function", "execute") in kinds_and_names
    assert ("macro", "my_macro") in kinds_and_names

    spans = strategy.extract_spans("src/config.rs", rust_code, len(rust_code.splitlines()))
    assert any(s.kind == "preamble" for s in spans)
    assert any(s.title == "Config" for s in spans)

    evidence = strategy.extract_evidence("src/config.rs", rust_code)
    assert "std::collections::HashMap" in evidence.imports
    assert "Config" in evidence.exports
    assert "Status" in evidence.exports
    assert "Runner" in evidence.exports
    assert "execute" in evidence.exports
    assert any("Crate documentation" in h for h in evidence.doc_hints)


def test_go_strategy_extraction() -> None:
    go_code = """package server

import (
    "context"
    "fmt"
)

type Server struct {
    port int
}

type Handler interface {
    Handle(ctx context.Context) error
}

type Status int

func NewServer(port int) *Server {
    return &Server{port: port}
}

func (s *Server) Start() error {
    fmt.Println(s.port)
    return nil
}

func (s Server) unexported() {}
"""
    strategy = GoStrategy()
    symbols = strategy.extract_symbols("server.go", go_code)
    kinds_and_names = [(s.kind, s.name) for s in symbols]

    assert ("struct", "Server") in kinds_and_names
    assert ("interface", "Handler") in kinds_and_names
    assert ("type", "Status") in kinds_and_names
    assert ("function", "NewServer") in kinds_and_names
    assert ("method", "Server.Start") in kinds_and_names
    assert ("method", "Server.unexported") in kinds_and_names

    spans = strategy.extract_spans("server.go", go_code, len(go_code.splitlines()))
    assert any(s.kind == "preamble" for s in spans)
    assert any(s.title == "Server" for s in spans)
    assert any(s.title == "Server.Start" for s in spans)

    evidence = strategy.extract_evidence("server.go", go_code)
    assert evidence.package == "server"
    assert "context" in evidence.imports
    assert "fmt" in evidence.imports
    # Go exports capital identifiers
    assert "Server" in evidence.exports
    assert "Handler" in evidence.exports
    assert "Status" in evidence.exports
    assert "NewServer" in evidence.exports
    assert "Server.Start" in evidence.exports
    assert "Server.unexported" not in evidence.exports
    assert evidence.companion_path == "server_test.go"


def test_cpp_strategy_extraction() -> None:
    cpp_code = """#include <iostream>
#include "engine/vector.hpp"

namespace graphics {

class Renderer {
public:
    Renderer();
    ~Renderer();
    void render();
};

struct Vertex {
    float x, y, z;
};

enum class ColorFormat {
    RGBA,
    RGB,
};

Renderer::Renderer() {
}

Renderer::~Renderer() {
}

void Renderer::render() {
}

template<typename T>
T clamp(T val, T min_v, T max_v) {
    return val < min_v ? min_v : (val > max_v ? max_v : val);
}

int calculate_fps(int frames, double elapsed) {
    return frames / elapsed;
}

}
"""
    strategy = CppStrategy()
    symbols = strategy.extract_symbols("src/renderer.cpp", cpp_code)
    names = [(s.kind, s.name) for s in symbols]

    assert ("class", "Renderer") in names
    assert ("struct", "Vertex") in names
    assert ("enum", "ColorFormat") in names
    assert ("constructor", "Renderer::Renderer") in names
    assert ("destructor", "Renderer::~Renderer") in names
    assert ("method", "Renderer::render") in names
    assert ("function", "clamp") in names
    assert ("function", "calculate_fps") in names

    evidence = strategy.extract_evidence("src/renderer.cpp", cpp_code)
    assert evidence.namespace == "graphics"
    assert "iostream" in evidence.imports
    assert "engine/vector.hpp" in evidence.imports
    assert evidence.companion_path == "src/renderer.hpp"

    # Header to source companion resolution
    header_evidence = strategy.extract_evidence("src/renderer.hpp", "")
    assert header_evidence.companion_path == "src/renderer.cpp"


def test_ts_js_strategy_extraction() -> None:
    ts_code = """import { useState } from 'react';
import axios from 'axios';

/**
 * Service options
 */
export interface ServiceOptions {
    baseUrl: string;
}

export type ID = string | number;

export class ApiService {
    constructor(private options: ServiceOptions) {}
}

export const fetchUsers = async () => {
    return [];
};

export function initializeApp(name: string): void {
    console.log(name);
}

export const API_VERSION = "v1";
"""
    strategy = TsJsStrategy()
    symbols = strategy.extract_symbols("src/api.ts", ts_code)
    names = [(s.kind, s.name) for s in symbols]

    assert ("interface", "ServiceOptions") in names
    assert ("type", "ID") in names
    assert ("class", "ApiService") in names
    assert ("function", "fetchUsers") in names
    assert ("function", "initializeApp") in names
    assert ("symbol", "API_VERSION") in names

    spans = strategy.extract_spans("src/api.ts", ts_code, len(ts_code.splitlines()))
    assert any(s.kind == "preamble" for s in spans)
    assert any(s.title == "ApiService" for s in spans)
    assert any(s.title == "fetchUsers" for s in spans)

    evidence = strategy.extract_evidence("src/api.ts", ts_code)
    assert "react" in evidence.imports
    assert "axios" in evidence.imports
    assert "ServiceOptions" in evidence.exports
    assert "ID" in evidence.exports
    assert "ApiService" in evidence.exports
    assert "fetchUsers" in evidence.exports
    assert "initializeApp" in evidence.exports
    assert "API_VERSION" in evidence.exports
    assert any("Service options" in h for h in evidence.doc_hints)
    assert evidence.companion_path == "src/api.test.ts"


def test_generic_strategy_markdown_and_fallback() -> None:
    md_text = """# Project Title

Some introductory text.

## Installation

Run setup commands here.

## Usage Guide

Use the tool as follows.
"""
    strategy = GenericStrategy()
    symbols = strategy.extract_symbols("README.md", md_text)
    assert len(symbols) == 3
    assert symbols[0].name == "Project Title"
    assert symbols[0].kind == "title"
    assert symbols[1].name == "Installation"
    assert symbols[1].kind == "section"
    assert symbols[2].name == "Usage Guide"
    assert symbols[2].kind == "section"

    spans = strategy.extract_spans("README.md", md_text, len(md_text.splitlines()))
    assert len(spans) == 3
    assert spans[0].title == "Project Title"

    evidence = strategy.extract_evidence("README.md", md_text)
    assert "title Project Title" in evidence.declarations


def test_language_indexing_router_routing() -> None:
    router = get_language_router()

    assert router.get_strategy("main.py").name == "python"
    assert router.get_strategy("Foo.java").name == "jvm"
    assert router.get_strategy("Bar.kt").name == "jvm"
    assert router.get_strategy("lib.rs").name == "rust"
    assert router.get_strategy("server.go").name == "go"
    assert router.get_strategy("matrix.cpp").name == "cpp"
    assert router.get_strategy("matrix.hpp").name == "cpp"
    assert router.get_strategy("app.ts").name == "ts_js"
    assert router.get_strategy("app.jsx").name == "ts_js"
    assert router.get_strategy("README.md").name == "generic"
    assert router.get_strategy("build.unknown").name == "generic"

    # Router delegation methods
    py_symbols = router.extract_symbols("test.py", "def hello(): pass")
    assert len(py_symbols) == 1
    assert py_symbols[0].name == "hello"

    py_spans = router.extract_spans("test.py", "def hello(): pass", 1)
    assert len(py_spans) == 1
    assert py_spans[0].title == "hello"

    py_evidence = router.extract_evidence("test.py", "def hello(): pass")
    assert "def hello" in py_evidence.declarations
