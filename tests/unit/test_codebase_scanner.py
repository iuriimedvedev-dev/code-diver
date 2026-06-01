from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.services import CodebaseScanner


pytestmark = pytest.mark.unit


def test_scanner_chunks_text_files_and_preserves_line_ranges(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    items = CodebaseScanner(include=["*.py"], chunk_lines=2).scan(tmp_path)

    assert [item.start_line for item in items] == [1, 3, 5]
    assert [item.end_line for item in items] == [2, 4, 5]
    assert all(item.path == "sample.py" for item in items)


def test_scanner_skips_binary_and_excluded_paths(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "skip.py").write_text("print('skip')\n", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"abc\x00def")
    nested = tmp_path / "generated" / "nested.py"
    nested.parent.mkdir()
    nested.write_text("print('generated')\n", encoding="utf-8")

    items = CodebaseScanner(include=["*.py"], exclude=["skip.py", "generated/**"]).scan(tmp_path)

    assert [item.path for item in items] == ["keep.py"]


def test_scanner_can_chunk_python_symbols(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
class UserService:
    def create_user(self):
        return "created"

def build_app():
    return UserService()
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], symbol_chunks=True).scan(tmp_path)

    titles = {item.title for item in items}
    assert "app.py" in titles
    assert "app.py::UserService" in titles
    assert "app.py::UserService.create_user" in titles
    assert "app.py::build_app" in titles
    assert all(item.metadata["source"] == "scanner" for item in items)


def test_scanner_can_use_structural_chunks(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
import os


class UserService:
    def create_user(self):
        return os.getenv("USER")


def build_app():
    return UserService()
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], chunk_lines=20, structural_chunks=True).scan(tmp_path)

    structural = [item for item in items if item.metadata["index_kind"] == "structural_chunk"]
    assert [item.title for item in structural] == [
        "app.py::module preamble",
        "app.py::UserService",
        "app.py::build_app",
    ]
    assert [(item.start_line, item.end_line) for item in structural] == [(1, 3), (4, 6), (9, 10)]


def test_scanner_can_add_file_summary_items(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        """
from services.auth import authorize

class UserService:
    def create_user(self):
        return authorize()
""".strip(),
        encoding="utf-8",
    )

    items = CodebaseScanner(include=["*.py"], symbol_chunks=True, file_summary_chunks=True).scan(tmp_path)

    summaries = [item for item in items if item.metadata["index_kind"] == "file_summary"]
    assert len(summaries) == 1
    assert summaries[0].path == "app.py"
    assert "imports:" in summaries[0].content
    assert "symbols:" in summaries[0].content
    assert "UserService.create_user" in summaries[0].content
