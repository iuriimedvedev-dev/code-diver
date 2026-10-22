"""The version surfaces: --version, `info`, and the MCP serverInfo handshake.

A version that cannot say 'dirty' makes a benchmark row unreproducible, so these tests pin
the three places an operator or a client actually reads the value.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from code_diver import __version__, build_version
from code_diver.cli import main
from code_diver.transport.mcp_http import SERVER_NAME, initialize_result


def test_build_version_reports_dirty_from_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "f.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    clean = build_version(tmp_path)
    assert clean and "-dirty" not in clean
    (tmp_path / "f.txt").write_text("changed", encoding="utf-8")
    assert build_version(tmp_path).endswith("-dirty")


def test_build_version_falls_back_to_the_constant_without_git(tmp_path: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise OSError("git is not installed")
    monkeypatch.setattr("code_diver.subprocess.run", boom)
    assert build_version(tmp_path) == __version__


def test_cli_version_exits_zero_and_prints_the_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("code-diver ")
    assert build_version() in out


def _json_config(tmp_path: Path) -> Path:
    artifact = tmp_path / "index.json"
    artifact.write_text(
        json.dumps({"schema_version": 1, "provider": "openai_compatible", "model": "test-model",
                    "dimensions": 8, "items": []}),
        encoding="utf-8",
    )
    cfg = tmp_path / "config.yml"
    cfg.write_text(f"root: {tmp_path}\nartifact: {artifact}\nstorage:\n  provider: json\n", encoding="utf-8")
    return cfg


def test_info_text_shows_the_version(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(_json_config(tmp_path)), "info"]) == 0
    out = capsys.readouterr().out
    assert "Version" in out
    assert build_version() in out


def test_info_json_carries_the_version(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(_json_config(tmp_path)), "info", "-j"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["version"] == build_version()


def test_mcp_initialize_server_info_carries_the_version() -> None:
    result = initialize_result("2025-06-18")
    assert result["serverInfo"]["name"] == SERVER_NAME
    assert result["serverInfo"]["version"] == build_version()
