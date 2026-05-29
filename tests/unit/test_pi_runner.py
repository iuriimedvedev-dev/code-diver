from __future__ import annotations

from pathlib import Path

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
