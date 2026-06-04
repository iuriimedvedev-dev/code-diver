from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from ..settings import Defaults, EnvironmentVariable, OptionName, VectorStoreProviderId


class PiCommandBuilder:
    def build(
        self,
        config: AppConfig,
        prompt: str | None = None,
        print_mode: bool = False,
        toolset: str | None = None,
        hypothesis: str | None = None,
        model: str | None = None,
    ) -> list[str]:
        pi_config = config.pi
        command = [pi_config.binary, *pi_config.launcher_args]
        if print_mode:
            command.append(OptionName.PRINT.value)

        command.extend([OptionName.EXTENSION.value, str(pi_config.extension)])

        if pi_config.prompt_template:
            command.extend([OptionName.PROMPT_TEMPLATE.value, str(pi_config.prompt_template)])

        if pi_config.provider:
            command.extend([OptionName.PROVIDER.value, pi_config.provider])

        selected_model = model or pi_config.model
        if selected_model:
            command.extend([OptionName.MODEL.value, selected_model])

        tools = self._tools(config, toolset, hypothesis)
        if tools:
            command.extend([OptionName.TOOLS.value, ",".join(tools)])

        command.extend(pi_config.extra_args)
        if prompt:
            command.append(prompt)
        return command

    def env(
        self,
        config: AppConfig,
        config_path: Path | None,
        toolset: str | None = None,
        hypothesis: str | None = None,
    ) -> dict[str, str]:
        env = {
            EnvironmentVariable.CODE_DIVER_CONFIG.value: str((config_path or Defaults.CONFIG_PATH).resolve()),
            EnvironmentVariable.CODE_DIVER_ROOT.value: str(config.root.resolve()),
        }
        if config.storage.provider == VectorStoreProviderId.QDRANT.value:
            env[EnvironmentVariable.CODE_DIVER_QDRANT_COLLECTION.value] = config.storage.qdrant.collection
        if toolset:
            env["CODE_DIVER_TOOLSET"] = toolset
        if hypothesis:
            env["CODE_DIVER_HYPOTHESIS"] = hypothesis
        env.update(config.pi.env)
        return env

    def _tools(self, config: AppConfig, toolset: str | None, hypothesis: str | None) -> list[str]:
        pi_config = config.pi
        if hypothesis:
            selected = next(
                (candidate for candidate in config.experiments.hypotheses if candidate.name == hypothesis),
                None,
            )
            if selected is None:
                raise ValueError(f"Unknown experiment hypothesis: {hypothesis}")
            if selected.tools:
                return selected.tools
            if selected.toolset:
                return self._toolset(pi_config.toolsets, selected.toolset)
        if not toolset:
            return pi_config.tools
        return self._toolset(pi_config.toolsets, toolset)

    def _toolset(self, toolsets: dict[str, list[str]], toolset: str) -> list[str]:
        if toolset not in toolsets:
            raise ValueError(f"Unknown Search agent toolset: {toolset}")
        return toolsets[toolset]
