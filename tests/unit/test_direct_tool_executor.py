from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_diver.agent.direct_tool_executor import DirectToolExecutor
from code_diver.agent.tool_call import ToolCall


pytestmark = pytest.mark.unit


def test_direct_tool_executor_returns_structured_rg_without_text_by_default(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class AuthService:\n    def login(self):\n        return True\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_rg"]).execute(
        ToolCall("code_diver_rg", {"pattern": "AuthService|login", "path": "src", "limit": 10})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["tool"] == "code_diver_rg"
    assert payload["metrics"]["matchCount"] == 2
    assert payload["result"]["candidates"][0]["path"] == "src/service.py"
    assert payload["result"]["matches"][0] == {"path": "src/service.py", "line": 1}


def test_direct_tool_executor_read_returns_bounded_source_on_request(tmp_path: Path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("line one\nline two\nline three\n", encoding="utf-8")

    result = DirectToolExecutor(tmp_path, ["code_diver_read"]).execute(
        ToolCall("code_diver_read", {"file": "src/service.py", "startLine": 2, "lines": 1})
    )

    payload = json.loads(result.content)
    assert payload["ok"] is True
    assert payload["result"]["path"] == "src/service.py"
    assert payload["result"]["lines"] == [{"line": 2, "text": "line two"}]
