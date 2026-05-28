from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..config import AppConfig
from .pi_command_builder import PiCommandBuilder


class PiRunner:
    def __init__(self, command_builder: PiCommandBuilder | None = None):
        self.command_builder = command_builder or PiCommandBuilder()

    def run_interactive(self, config: AppConfig, config_path: Path | None, prompt: str | None = None) -> int:
        command = self.command_builder.build(config, prompt=prompt, print_mode=False)
        env = self._env(config, config_path)
        return subprocess.call(command, env=env)

    def run_print(self, config: AppConfig, config_path: Path | None, prompt: str) -> int:
        command = self.command_builder.build(config, prompt=prompt, print_mode=True)
        env = self._env(config, config_path)
        return subprocess.call(command, env=env)

    def _env(self, config: AppConfig, config_path: Path | None) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.command_builder.env(config, config_path))
        return env
