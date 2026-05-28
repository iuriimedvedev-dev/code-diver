from __future__ import annotations

from ..config import AppConfig
from ..settings import Defaults, EnvironmentVariable, OptionName


class PiCommandBuilder:
    def build(self, config: AppConfig, prompt: str | None = None, print_mode: bool = False) -> list[str]:
        pi_config = config.pi
        command = [pi_config.binary]
        if print_mode:
            command.append(OptionName.PRINT.value)

        command.extend([OptionName.EXTENSION.value, str(pi_config.extension)])

        if pi_config.prompt_template:
            command.extend([OptionName.PROMPT_TEMPLATE.value, str(pi_config.prompt_template)])

        if pi_config.provider:
            command.extend([OptionName.PROVIDER.value, pi_config.provider])

        if pi_config.model:
            command.extend([OptionName.MODEL.value, pi_config.model])

        if pi_config.tools:
            command.extend([OptionName.TOOLS.value, ",".join(pi_config.tools)])

        command.extend(pi_config.extra_args)
        if prompt:
            command.append(prompt)
        return command

    def env(self, config: AppConfig, config_path: Path | None) -> dict[str, str]:
        env = {
            EnvironmentVariable.CODE_DIVER_CONFIG.value: str((config_path or Defaults.CONFIG_PATH).resolve()),
            EnvironmentVariable.CODE_DIVER_ROOT.value: str(config.root.resolve()),
        }
        env.update(config.pi.env)
        return env
