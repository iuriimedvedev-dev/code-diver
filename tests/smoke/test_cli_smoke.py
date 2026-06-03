from __future__ import annotations

import pytest

from code_diver.cli import main


pytestmark = pytest.mark.smoke


def test_cli_help_smoke(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "index" in output
    assert "search" in output
    assert "evaluate" in output
    assert "evaluate-search-tools" not in output
    assert "tree" not in output


def test_cli_help_all_smoke(capsys) -> None:
    assert main(["--help-all"]) == 0

    output = capsys.readouterr().out
    assert "evaluate-search-tools" in output
    assert "tree" in output
    assert "grep" in output
    assert "rg" in output
