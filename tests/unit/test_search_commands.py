from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_diver.commands.search import (
    cmd_search,
    format_search_result,
    normalize_query,
    result_to_json,
    run_search,
    search_output_formatter,
    sort_results_by_score,
)
from code_diver.config import AppConfig
from code_diver.domain.code_item import CodeItem
from code_diver.domain.search_result import SearchResult


def test_normalize_query() -> None:
    assert normalize_query(None) == ""
    assert normalize_query("  foo bar  ") == "foo bar"
    assert normalize_query(["foo", "bar"]) == "foo bar"


def test_search_output_formatter_and_result_to_json() -> None:
    item = CodeItem(
        id="item-1",
        path="foo.py",
        title="foo",
        start_line=1,
        end_line=10,
        content="print('foo')",
    )
    res1 = SearchResult(item=item, score=0.85)
    res2 = SearchResult(item=item, score=0.95)

    single_json = result_to_json(res1)
    assert single_json["score"] == 0.85
    assert single_json["item"]["path"] == "foo.py"
    assert format_search_result(res1) == single_json

    formatted_list = search_output_formatter([res1, res2])
    assert isinstance(formatted_list, list)
    assert len(formatted_list) == 2
    assert formatted_list[0]["score"] == 0.85
    assert formatted_list[1]["score"] == 0.95

    formatted_str = search_output_formatter([res1], as_json=True)
    assert isinstance(formatted_str, str)
    parsed = json.loads(formatted_str)
    assert parsed[0]["score"] == 0.85

    sorted_res = sort_results_by_score([res1, res2])
    assert sorted_res[0].score == 0.95
    assert sorted_res[1].score == 0.85


def test_cmd_search_requires_query_when_not_interactive(capsys: pytest.CaptureFixture) -> None:
    config = AppConfig()
    args = argparse.Namespace(query=None, interactive=False, json=False)
    exit_code = cmd_search(args, config)
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "search query is required unless -i/--interactive is used" in err


def test_cmd_search_json_output(capsys: pytest.CaptureFixture) -> None:
    config = AppConfig()
    item = CodeItem(
        id="item-1",
        path="test.py",
        title="test",
        start_line=1,
        end_line=5,
        content="def test(): pass",
    )
    mock_results = [SearchResult(item=item, score=0.99)]

    args = argparse.Namespace(query="test", interactive=False, json=True, limit=5, config=None)
    with patch("code_diver.commands.search.run_search", return_value=mock_results):
        exit_code = cmd_search(args, config)
        assert exit_code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["score"] == 0.99
        assert data[0]["item"]["path"] == "test.py"


def test_cmd_search_agent_unavailable_deterministic_fallback() -> None:
    config = AppConfig()
    item = CodeItem(
        id="item-1",
        path="test.py",
        title="test",
        start_line=1,
        end_line=5,
        content="def test(): pass",
    )
    mock_results = [SearchResult(item=item, score=0.99)]

    args = argparse.Namespace(query="test", interactive=False, json=False, limit=5, config=None)
    with (
        patch("code_diver.commands.search.code_explorer_preflight", return_value=True),
        patch("code_diver.commands.search.search_agent_binary_available", return_value=False),
        patch("code_diver.commands.search.run_search", return_value=mock_results),
        patch("code_diver.commands.search.SearchRenderer") as mock_renderer_cls,
    ):
        mock_renderer = MagicMock()
        mock_renderer_cls.return_value = mock_renderer
        exit_code = cmd_search(args, config)
        assert exit_code == 0
        mock_renderer.render.assert_called_once_with("test", mock_results)
