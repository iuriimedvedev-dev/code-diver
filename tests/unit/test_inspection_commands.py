from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from code_diver.commands.inspection import (
    cmd_grep,
    cmd_info,
    cmd_open,
    cmd_read,
    cmd_rg,
    cmd_symbols,
    cmd_tree,
    format_open_location,
    normalize_query,
    print_inspection_error,
    render_info_metrics,
)
from code_diver.config import AppConfig
from code_diver.config.storage_config import StorageConfig
from code_diver.domain.code_item import CodeItem
from code_diver.domain.search_result import SearchResult
from code_diver.inspection.info_service import InfoService


def test_normalize_query() -> None:
    assert normalize_query("  foo bar  ") == "foo bar"
    assert normalize_query(["foo", "bar", "baz"]) == "foo bar baz"


def test_format_open_location() -> None:
    assert format_open_location("path/to/file.py") == "path/to/file.py"
    assert format_open_location("path/to/file.py", 42) == "path/to/file.py:42"


def test_print_inspection_error() -> None:
    buf = io.StringIO()
    code = print_inspection_error("something failed", file=buf)
    assert code == 1
    assert "error: something failed\n" == buf.getvalue()


def test_inspection_commands(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (repo / "hello.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
    (repo / "ignored.py").write_text("def secret():\n    pass\n", encoding="utf-8")

    config = AppConfig(root=repo)

    # cmd_tree
    args = argparse.Namespace(path=None, depth=3, limit=100)
    assert cmd_tree(args, config) == 0
    out = capsys.readouterr().out
    assert "hello.py" in out
    assert "ignored.py" not in out

    # cmd_grep
    args = argparse.Namespace(pattern="greet", path=None, limit=100)
    assert cmd_grep(args, config) == 0
    out = capsys.readouterr().out
    assert "hello.py:1" in out

    # cmd_rg
    args = argparse.Namespace(pattern="greet", path=None, limit=100)
    assert cmd_rg(args, config) == 0
    out = capsys.readouterr().out
    assert "hello.py:1" in out

    # cmd_read
    args = argparse.Namespace(file="hello.py", start_line=1, lines=2)
    assert cmd_read(args, config) == 0
    out = capsys.readouterr().out
    assert "hello.py:1-2" in out
    assert "def greet():" in out

    # cmd_symbols
    args = argparse.Namespace(path="hello.py", limit=100)
    assert cmd_symbols(args, config) == 0
    out = capsys.readouterr().out
    assert "function greet" in out


def test_cmd_info(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    json_artifact = tmp_path / "index.json"
    json_artifact.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "openai_compatible",
                "model": "test-model",
                "dimensions": 768,
                "items": [],
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        root=tmp_path,
        artifact=json_artifact,
        storage=StorageConfig(provider="json"),
    )

    # rich output
    args = argparse.Namespace(json=False)
    assert cmd_info(args, config) == 0
    out = capsys.readouterr().out
    assert "Code Diver Index & Storage Overview" in out
    assert "Vector Store" in out

    # json output
    args = argparse.Namespace(json=True)
    assert cmd_info(args, config) == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["store"]["provider"] == "json"


def test_render_info_metrics(tmp_path: Path) -> None:
    config = AppConfig(root=tmp_path, storage=StorageConfig(provider="json"))
    service = InfoService(config)
    info = service.get_info()
    table = render_info_metrics(info)
    assert table.title == "[bold cyan]Code Diver Index & Storage Overview[/bold cyan]"


def test_cmd_open(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = AppConfig(root=tmp_path)
    item = CodeItem(
        id="item-1",
        path="foo.py",
        title="foo",
        start_line=10,
        end_line=20,
        content="x = 1",
    )
    mock_result = SearchResult(item=item, score=0.95)

    def mock_search(cfg: AppConfig, q: str, limit: int) -> list[SearchResult]:
        if q == "empty":
            return []
        return [mock_result]

    # Empty results
    args = argparse.Namespace(rank=1, query=["empty"])
    assert cmd_open(args, config, search_fn=mock_search) == 1
    assert "No search results." in capsys.readouterr().out

    # Rank out of bounds
    args = argparse.Namespace(rank=2, query=["foo"])
    assert cmd_open(args, config, search_fn=mock_search) == 1
    assert "Only 1 search results available." in capsys.readouterr().out

    # Successful open
    args = argparse.Namespace(rank=1, query=["foo"])
    assert cmd_open(args, config, search_fn=mock_search) == 0
    out = capsys.readouterr().out
    assert "Opened foo.py:10 with:" in out
