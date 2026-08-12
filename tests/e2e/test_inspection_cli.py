from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.cli import main

pytestmark = pytest.mark.e2e


def test_inspection_cli_commands_are_read_only_and_gitignore_aware(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (repo / "app.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    (repo / "ignored.py").write_text("def target():\n    return 2\n", encoding="utf-8")
    config = tmp_path / "code-diver.yml"
    config.write_text(f"root: {repo}\nembedding:\n  provider: hash\n", encoding="utf-8")

    assert main(["--config", str(config), "tree"]) == 0
    tree_output = capsys.readouterr().out
    assert "app.py" in tree_output
    assert "ignored.py" not in tree_output

    assert main(["--config", str(config), "grep", "target"]) == 0
    grep_output = capsys.readouterr().out
    assert "app.py:1" in grep_output
    assert "ignored.py" not in grep_output

    assert main(["--config", str(config), "rg", "target"]) == 0
    rg_output = capsys.readouterr().out
    assert "app.py:1" in rg_output

    assert main(["--config", str(config), "symbols", "--path", "app.py"]) == 0
    symbols_output = capsys.readouterr().out
    assert "app.py:1: function target" in symbols_output
    assert "ignored.py" not in symbols_output

    assert main(["--config", str(config), "read", "app.py", "--start-line", "1", "--lines", "1"]) == 0
    read_output = capsys.readouterr().out
    assert "app.py:1-1" in read_output
    assert "def target" in read_output
