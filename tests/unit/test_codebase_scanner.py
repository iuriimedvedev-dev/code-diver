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
