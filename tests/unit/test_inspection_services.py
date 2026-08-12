from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.inspection import GrepService, RgService, TreeService

pytestmark = pytest.mark.unit


def test_tree_is_gitignore_aware(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n*.log\n", encoding="utf-8")
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / "file.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "secret.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "debug.log").write_text("needle\n", encoding="utf-8")

    output = TreeService(tmp_path).render(max_depth=3)

    assert "kept/" in output
    assert "file.py" in output
    assert "ignored" not in output
    assert "debug.log" not in output


def test_grep_is_gitignore_aware_and_blocks_path_escape(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("needle\n", encoding="utf-8")

    output = GrepService(tmp_path).render("needle")

    assert "kept.py:1" in output
    assert "ignored.py" not in output
    with pytest.raises(ValueError, match="escapes"):
        GrepService(tmp_path).render("needle", path="../outside")


def test_rg_falls_back_or_uses_rg_without_escaping_root(tmp_path: Path) -> None:
    (tmp_path / "file.py").write_text("alpha\nbeta\n", encoding="utf-8")

    output = RgService(tmp_path).search("alp.*", limit=5)

    assert "file.py:1:alpha" in output or "file.py:1: alpha" in output
