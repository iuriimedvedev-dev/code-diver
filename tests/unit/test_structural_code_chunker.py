from __future__ import annotations

import pytest

from code_diver.domain import CodeItemIndexKind, CodeItemMetadata
from code_diver.indexing import LanguageIndexingRouter
from code_diver.services import StructuralCodeChunker

pytestmark = pytest.mark.unit


def test_structural_code_chunker_python_spans() -> None:
    code = """import os

class UserService:
    def create_user(self):
        return os.getenv("USER")

def build_app():
    return UserService()
""".strip()

    chunker = StructuralCodeChunker(max_lines=50)
    items = chunker.chunk("app.py", code)

    assert len(items) == 3
    assert [item.title for item in items] == [
        "app.py::module preamble",
        "app.py::UserService",
        "app.py::build_app",
    ]
    assert [(item.start_line, item.end_line) for item in items] == [
        (1, 2),
        (3, 5),
        (7, 8),
    ]
    for item in items:
        assert item.metadata[CodeItemMetadata.SOURCE] == "scanner"
        assert item.metadata[CodeItemMetadata.INDEX_KIND] == CodeItemIndexKind.STRUCTURAL_CHUNK
        assert item.path == "app.py"


def test_structural_code_chunker_jvm_spans() -> None:
    java_code = """package com.diver.test;

import java.util.List;

public class UserService {
    public void run() {
    }
}
""".strip()

    chunker = StructuralCodeChunker(max_lines=50)
    items = chunker.chunk("src/UserService.java", java_code)

    titles = [item.title for item in items]
    assert any("preamble" in t for t in titles)
    assert any("UserService" in t for t in titles)
    assert all(item.metadata[CodeItemMetadata.INDEX_KIND] == CodeItemIndexKind.STRUCTURAL_CHUNK for item in items)


def test_structural_code_chunker_rust_spans() -> None:
    rust_code = """//! Rust crate doc

pub struct AppConfig {
    pub port: u16,
}

pub fn run_server() {
}
""".strip()

    chunker = StructuralCodeChunker(max_lines=50)
    items = chunker.chunk("src/main.rs", rust_code)

    titles = [item.title for item in items]
    assert any("preamble" in t for t in titles)
    assert any("AppConfig" in t for t in titles)
    assert any("run_server" in t for t in titles)


def test_structural_code_chunker_go_spans() -> None:
    go_code = """package main

import "fmt"

type Server struct {
    port int
}

func (s *Server) Start() {
    fmt.Println(s.port)
}
""".strip()

    chunker = StructuralCodeChunker(max_lines=50)
    items = chunker.chunk("server.go", go_code)

    titles = [item.title for item in items]
    assert any("preamble" in t for t in titles)
    assert any("Server" in t for t in titles)
    assert any("Server.Start" in t for t in titles)


def test_structural_code_chunker_ts_spans() -> None:
    ts_code = """import { useState } from 'react';

export class AppClient {
    execute() {}
}

export function initialize() {}
""".strip()

    chunker = StructuralCodeChunker(max_lines=50)
    items = chunker.chunk("src/client.ts", ts_code)

    titles = [item.title for item in items]
    assert any("preamble" in t for t in titles)
    assert any("AppClient" in t for t in titles)
    assert any("initialize" in t for t in titles)


def test_structural_code_chunker_generic_markdown() -> None:
    md_text = """# Main Header

Some introductory remarks.

## Getting Started

Follow these steps.
""".strip()

    chunker = StructuralCodeChunker(max_lines=50)
    items = chunker.chunk("docs/README.md", md_text)

    titles = [item.title for item in items]
    assert "docs/README.md::Main Header" in titles
    assert "docs/README.md::Getting Started" in titles


def test_structural_code_chunker_sub_chunking_large_blocks() -> None:
    # 30-line function with max_lines=10 should be split into 3 chunks
    lines = ["def huge_function():"] + [f"    x = {i}" for i in range(29)]
    code = "\n".join(lines)

    chunker = StructuralCodeChunker(max_lines=10)
    items = chunker.chunk("huge.py", code)

    assert len(items) == 3
    assert items[0].start_line == 1
    assert items[0].end_line == 10
    assert items[1].start_line == 11
    assert items[1].end_line == 20
    assert items[2].start_line == 21
    assert items[2].end_line == 30
    assert ":1-10" in items[0].title
    assert ":11-20" in items[1].title
    assert ":21-30" in items[2].title


def test_structural_code_chunker_empty_input() -> None:
    chunker = StructuralCodeChunker(max_lines=50)
    assert chunker.chunk("empty.py", "") == []
    assert chunker.chunk("empty.py", "   \n\n   ") == []


def test_structural_code_chunker_custom_router() -> None:
    custom_router = LanguageIndexingRouter()
    chunker = StructuralCodeChunker(max_lines=50, router=custom_router)
    assert chunker.router is custom_router
