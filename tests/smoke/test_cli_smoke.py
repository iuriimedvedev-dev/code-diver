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
    assert "provider" in output
    assert "evaluate-search-tools" not in output
    assert "tree" not in output


def test_provider_test_help_smoke(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["provider", "test", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--fallback-chain" in output
    assert "--skip-generation" in output


def test_cli_help_all_smoke(capsys) -> None:
    assert main(["--help-all"]) == 0

    output = capsys.readouterr().out
    assert "evaluate-search-tools" in output
    assert "tree" in output
    assert "grep" in output
    assert "rg" in output
    assert "serve" in output
    assert "acp" in output
    assert "mcp" in output


def test_serve_help_smoke(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["serve", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--http-port" in output
    assert "--grpc-port" in output
    assert "--host" in output


def test_acp_help_smoke(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["acp", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "usage: code-diver acp" in output


def test_mcp_help_smoke(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["mcp", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "usage: code-diver mcp" in output


def test_index_help_mentions_clear(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["index", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "index_root|clear" in output
    assert "delete Qdrant index collections" in output


def test_index_clear_help_smoke(capsys) -> None:
    assert main(["index", "clear", "--help"]) == 0

    output = capsys.readouterr().out
    assert "usage: code-diver index clear" in output
    assert "--all" in output
    assert "Delete all Code Diver index collections" in output
