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
    assert "code_diver_tree" in config.pi.tools
    assert "code_diver_grep" in config.pi.tools
    assert "code_diver_rg" in config.pi.tools
