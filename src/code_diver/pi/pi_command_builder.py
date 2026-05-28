from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import AppConfig


class PiCommandBuilder:
    def build(self, config: AppConfig, prompt: str | None = None, print_mode: bool = False) -> list[str]:
        pi_config = config.pi
        command = [str(pi_config.get("binary", "pi"))]
        if print_mode:
            command.append("-p")

        extension = Path(pi_config.get("extension", ".pi/extensions/code-diver-rag.ts"))
        command.extend(["--extension", str(extension)])

        prompt_template = pi_config.get("prompt_template")
        if prompt_template:
            command.extend(["--prompt-template", str(prompt_template)])

        provider = pi_config.get("provider")
        if provider:
            command.extend(["--provider", str(provider)])

        model = pi_config.get("model")
        if model:
            command.extend(["--model", str(model)])

        tools = list(pi_config.get("tools") or [])
        if tools:
            command.extend(["--tools", ",".join(str(tool) for tool in tools)])

        command.extend(str(value) for value in pi_config.get("extra_args") or [])
        if prompt:
            command.append(prompt)
        return command

    def env(self, config: AppConfig, config_path: Path | None) -> dict[str, str]:
        env = {
            "CODE_DIVER_CONFIG": str((config_path or Path("code-diver.yml")).resolve()),
            "CODE_DIVER_ROOT": str(config.root.resolve()),
        }
        env.update({str(key): str(value) for key, value in dict(config.pi.get("env") or {}).items()})
        return env
