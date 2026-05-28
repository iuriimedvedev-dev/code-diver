from __future__ import annotations

import pytest

from code_diver.cli import main


pytestmark = pytest.mark.smoke


def test_cli_help_smoke(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    assert "index" in capsys.readouterr().out
