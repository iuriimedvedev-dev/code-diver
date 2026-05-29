from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from code_diver.config.app_config import AppConfig
from code_diver.config.pi_config import PiConfig
from code_diver.pi import PiRunner


pytestmark = pytest.mark.unit


def test_pi_runner_tries_fallback_models(monkeypatch) -> None:
    config = AppConfig(
        root=Path("/repo"),
        pi=PiConfig(
            binary="pi",
            model="google/gemini-3.5-flash",
            fallback_models=["google/gemini-2.5-flash"],
        ),
    )
    commands: list[list[str]] = []

    def fake_call(command: list[str], env: dict[str, str]) -> int:
        commands.append(command)
        return 1 if len(commands) == 1 else 0

    monkeypatch.setattr("subprocess.call", fake_call)

    assert PiRunner().run_print(config, Path("code-diver.yml"), "hello") == 0
    assert commands[0][commands[0].index("--model") + 1] == "google/gemini-3.5-flash"
    assert commands[1][commands[1].index("--model") + 1] == "google/gemini-2.5-flash"


def test_pi_runner_writes_json_mode_log(monkeypatch, tmp_path: Path) -> None:
    config = AppConfig(root=Path("/repo"), pi=PiConfig(binary="pi", model="google/gemini-3.5-flash"))
    commands: list[list[str]] = []

    def fake_run(command: list[str], env: dict[str, str], capture_output: bool, text: bool, timeout: int):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='{"type":"agent_end"}\n', stderr="warn\n")

    monkeypatch.setattr("subprocess.run", fake_run)
    log_path = tmp_path / "pi.jsonl"

    assert PiRunner().run_print_logged(config, Path("code-diver.yml"), "hello", log_path) == 0

    assert "--mode" in commands[0]
    assert commands[0][commands[0].index("--mode") + 1] == "json"
    assert "hello" == commands[0][-1]
    text = log_path.read_text(encoding="utf-8")
    assert '{"type":"agent_end"}' in text
    assert '"type": "runner_stderr"' in text
