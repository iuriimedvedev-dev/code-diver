from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from threading import Thread
from typing import Any

from ..settings import Defaults
from .generation_result import GenerationResult
from .transient_generation_retry import TransientGenerationRetry


class AntigravitySdkGenerationProvider:
    def __init__(
        self,
        model: str = Defaults.ANTIGRAVITY_SDK_MODEL,
        api_key: str | None = None,
        vertex: bool | None = None,
        project: str | None = None,
        location: str | None = None,
        timeout_seconds: float = Defaults.GENERATION_TIMEOUT_MS / 1000,
        system_instructions: str | None = None,
        app_data_dir: str | None = None,
        save_dir: str | None = None,
        workspace: str | None = None,
        retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
    ):
        self.name = Defaults.ANTIGRAVITY_SDK_PROVIDER
        self.model = model or Defaults.ANTIGRAVITY_SDK_MODEL
        self.api_key = api_key
        self.vertex = vertex
        self.project = project
        self.location = location
        self.timeout_seconds = timeout_seconds
        self.system_instructions = (
            system_instructions or self._default_system_instructions()
        )
        self.app_data_dir = app_data_dir
        self.save_dir = save_dir
        self.workspace = workspace
        self.retry = TransientGenerationRetry(
            attempts=retry_attempts,
            base_delay_seconds=retry_base_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
        )

    def generate_json(self, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        return self.generate_json_result(prompt, schema=schema).text

    # `schema` is accepted and ignored: this backend cannot constrain decoding.
    # SchemaGuardedGenerationProvider validates and repairs the output instead.
    def generate_json_result(self, prompt: str, *, schema: dict[str, Any] | None = None) -> GenerationResult:
        return self.retry.run(lambda: self._run_sync(prompt))

    def _run_sync(self, prompt: str) -> GenerationResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                asyncio.wait_for(self._run(prompt), timeout=self.timeout_seconds)
            )

        result: GenerationResult | None = None
        error: BaseException | None = None

        def target() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(
                    asyncio.wait_for(self._run(prompt), timeout=self.timeout_seconds)
                )
            except (
                BaseException
            ) as exc:  # pragma: no cover - defensive path for async hosts
                error = exc

        thread = Thread(target=target, daemon=True)
        thread.start()
        thread.join(self.timeout_seconds + 1)
        if thread.is_alive():
            raise RuntimeError(
                f"Antigravity SDK timed out after {self.timeout_seconds:.1f}s"
            )
        if error is not None:
            raise RuntimeError(str(error)) from error
        if result is None:
            raise RuntimeError("Antigravity SDK returned no result.")
        return result

    async def _run(self, prompt: str) -> GenerationResult:
        try:
            from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
            from google.antigravity.hooks import policy
            from google.antigravity.types import BuiltinTools
        except (
            ImportError
        ) as exc:  # pragma: no cover - depends on optional dependency group
            raise RuntimeError(
                "Install Antigravity SDK with `uv sync --group antigravity-sdk` "
                "before using generation.provider=antigravity_sdk."
            ) from exc

        read_only_tools = [
            BuiltinTools.LIST_DIR,
            BuiltinTools.SEARCH_DIR,
            BuiltinTools.FIND_FILE,
            BuiltinTools.VIEW_FILE,
            BuiltinTools.FINISH,
        ]
        config_kwargs: dict[str, Any] = {
            "model": self.model,
            "system_instructions": self.system_instructions,
            "capabilities": CapabilitiesConfig(
                enable_subagents=False,
                enabled_tools=read_only_tools,
            ),
            "policies": [
                policy.deny("create_file"),
                policy.deny("edit_file"),
                policy.deny("run_command"),
                policy.deny("start_subagent"),
                policy.deny("generate_image"),
                policy.allow("*"),
            ],
        }
        workspace = self._expanded(self.workspace)
        if workspace:
            config_kwargs["workspaces"] = [workspace]
        app_data_dir = self._expanded(self.app_data_dir)
        if app_data_dir:
            config_kwargs["app_data_dir"] = app_data_dir
        save_dir = self._expanded(self.save_dir)
        if save_dir:
            config_kwargs["save_dir"] = save_dir
        if self.api_key:
            config_kwargs["api_key"] = self.api_key
        if self.vertex is not None:
            config_kwargs["vertex"] = self.vertex
        if self.project:
            config_kwargs["project"] = self.project
        if self.location:
            config_kwargs["location"] = self.location

        capture = _SdkWarningCapture()
        capture.install()
        try:
            async with Agent(LocalAgentConfig(**config_kwargs)) as agent:
                response = await agent.chat(prompt)
                text = (await response.text()).strip()
                if not text:
                    details = capture.summary()
                    suffix = f" Last SDK warning: {details}" if details else ""
                    raise RuntimeError(
                        f"Antigravity SDK returned an empty response.{suffix}"
                    )
                usage = response.usage_metadata
                return GenerationResult(
                    text=text,
                    model=self.model,
                    input_tokens=self._usage_int(usage, "prompt_token_count"),
                    output_tokens=self._usage_int(usage, "candidates_token_count"),
                    total_tokens=self._usage_int(usage, "total_token_count"),
                )
        finally:
            capture.uninstall()

    def _default_system_instructions(self) -> str:
        return (
            "Return exactly the requested answer. When asked for JSON, return valid JSON only. "
            "Do not edit, create, delete, move, or format files."
        )

    def _usage_int(self, usage: Any, name: str) -> int:
        return int(getattr(usage, name, 0) or 0) if usage is not None else 0

    def _expanded(self, value: str | None) -> str | None:
        if not value:
            return None
        return str(Path(os.path.expandvars(value)).expanduser())


class _SdkWarningCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self._records: list[str] = []
        self._logger = logging.getLogger()

    def install(self) -> None:
        self._logger.addHandler(self)

    def uninstall(self) -> None:
        self._logger.removeHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._records.append(record.getMessage())
        except Exception:  # pragma: no cover - logging must not break generation
            return

    def summary(self) -> str:
        if not self._records:
            return ""
        return self._records[-1]
