from __future__ import annotations

from pathlib import Path

import pytest

from code_diver.config import ConfigLoader


pytestmark = pytest.mark.unit


def test_default_pi_tools_exclude_write_capable_escape_hatches() -> None:
    config = ConfigLoader().load(Path("code-diver.yml"))

    assert "bash" not in config.pi.tools
    assert "read" not in config.pi.tools
    assert "grep" not in config.pi.tools
    assert "find" not in config.pi.tools
    assert "ls" not in config.pi.tools
    assert "code_diver_inspect" in config.pi.tools
    assert "code_diver_index_selected" in config.pi.tools
    assert "code_diver_tree" in config.pi.tools
    assert "code_diver_grep" in config.pi.tools
    assert "code_diver_rg" in config.pi.tools
    assert "code_diver_read" in config.pi.tools
    assert "code_diver_symbols" in config.pi.tools

    grep_tools = config.pi.toolsets["grep_search"]
    assert "code_diver_search" not in grep_tools
    assert "code_diver_index_selected" not in grep_tools
    assert {"code_diver_tree", "code_diver_rg", "code_diver_read"}.issubset(grep_tools)

    indexing_tools = config.pi.toolsets["indexing"]
    assert "code_diver_index_selected" in indexing_tools
    assert "bash" not in indexing_tools
    assert "read" not in indexing_tools
