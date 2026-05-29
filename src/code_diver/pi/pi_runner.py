from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from ..config import AppConfig
from .pi_command_builder import PiCommandBuilder


class PiRunner:
    def __init__(self, command_builder: PiCommandBuilder | None = None):
        self.command_builder = command_builder or PiCommandBuilder()

    def run_interactive(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str | None = None,
        toolset: str | None = None,
        hypothesis: str | None = None,
    ) -> int:
        return self._run_with_fallbacks(
            config,
            config_path,
            lambda model: self.command_builder.build(
                config,
                prompt=prompt,
                print_mode=False,
                toolset=toolset,
                hypothesis=hypothesis,
                model=model,
            ),
            toolset,
            hypothesis,
        )

    def run_print(
        self,
        config: AppConfig,
        config_path: Path | None,
        prompt: str,
        toolset: str | None = None,
        hypothesis: str | None = None,
    ) -> int:
        return self._run_with_fallbacks(
            config,
            config_path,
            lambda model: self.command_builder.build(
                config,
                prompt=prompt,
                print_mode=True,
                toolset=toolset,
                hypothesis=hypothesis,
                model=model,
            ),
            toolset,
            hypothesis,
        )

    def _env(
        self,
        config: AppConfig,
        config_path: Path | None,
        toolset: str | None = None,
        hypothesis: str | None = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.command_builder.env(config, config_path, toolset, hypothesis))
        return env

    def _run_with_fallbacks(
        self,
        config: AppConfig,
        config_path: Path | None,
        command_factory: Callable[[str | None], list[str]],
        toolset: str | None,
        hypothesis: str | None,
    ) -> int:
        env = self._env(config, config_path, toolset, hypothesis)
        last_code = 1
        for index, model in enumerate(self._models(config)):
            if index:
                print(f"Pi model fallback: {model}", file=sys.stderr)
            last_code = subprocess.call(command_factory(model), env=env)
            if last_code == 0:
                return 0
        return last_code

    def _models(self, config: AppConfig) -> list[str | None]:
        models: list[str | None] = []
        if config.pi.model:
            models.append(config.pi.model)
        for model in config.pi.fallback_models:
            if model not in models:
                models.append(model)
        return models or [None]
