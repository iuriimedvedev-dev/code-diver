from __future__ import annotations

import os

from ..config import AppConfig
from ..settings import Defaults
from .agy_cli_generation_provider import AgyCliGenerationProvider
from .antigravity_sdk_generation_provider import AntigravitySdkGenerationProvider
from .generation_provider import GenerationProvider
from .gemini_cli_generation_provider import GeminiCliGenerationProvider
from .gemini_generation_provider import GeminiGenerationProvider
from .openai_compatible_generation_provider import OpenAICompatibleGenerationProvider
from .openai_compatible_generation_provider_pool import (
    OpenAICompatibleGenerationProviderPool,
)
from .openai_generation_provider import OpenAIGenerationProvider
from .vertex_generation_provider import VertexGenerationProvider


def create_generation_provider(config: AppConfig) -> GenerationProvider:
    generation = config.generation
    if generation.provider == "gemini":
        return GeminiGenerationProvider(
            model=generation.model,
            fallback_models=generation.fallback_models,
            api_key=generation.api_key,
            temperature=generation.temperature,
            thinking_budget=generation.thinking_budget,
            api_version=generation.api_version,
            timeout_ms=generation.timeout_ms,
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    if generation.provider == Defaults.GEMINI_CLI_PROVIDER:
        return GeminiCliGenerationProvider(
            model=generation.model,
            binary=str(
                generation.extra_body.get("binary") or Defaults.GEMINI_CLI_BINARY
            ),
            timeout_seconds=generation.timeout_ms / 1000,
            approval_mode=str(
                generation.extra_body.get("approval_mode")
                or Defaults.GEMINI_CLI_APPROVAL_MODE
            ),
            skip_trust=bool(generation.extra_body.get("skip_trust", True)),
            output_format=str(generation.extra_body.get("output_format") or "json"),
            extra_args=_extra_args(generation.extra_body.get("extra_args", [])),
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    if generation.provider == Defaults.AGY_CLI_PROVIDER:
        return AgyCliGenerationProvider(
            model=generation.model or Defaults.AGY_CLI_MODEL,
            binary=str(generation.extra_body.get("binary") or Defaults.AGY_CLI_BINARY),
            timeout_seconds=generation.timeout_ms / 1000,
            print_timeout=str(
                generation.extra_body.get("print_timeout")
                or Defaults.AGY_CLI_PRINT_TIMEOUT
            ),
            sandbox=bool(generation.extra_body.get("sandbox", True)),
            extra_args=_extra_args(generation.extra_body.get("extra_args", [])),
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    if generation.provider == Defaults.ANTIGRAVITY_SDK_PROVIDER:
        return AntigravitySdkGenerationProvider(
            model=generation.model or Defaults.ANTIGRAVITY_SDK_MODEL,
            api_key=generation.api_key,
            vertex=_optional_bool(generation.extra_body.get("vertex")),
            project=generation.project,
            location=generation.location,
            timeout_seconds=generation.timeout_ms / 1000,
            system_instructions=_optional_str(
                generation.extra_body.get("system_instructions")
            ),
            app_data_dir=_optional_str(
                generation.extra_body.get("app_data_dir")
                or os.fspath(Defaults.ANTIGRAVITY_SDK_APP_DATA_DIR)
            ),
            save_dir=_optional_str(generation.extra_body.get("save_dir")),
            workspace=_optional_str(
                generation.extra_body.get("workspace") or config.root
            ),
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    if generation.provider == Defaults.VERTEX_PROVIDER:
        return VertexGenerationProvider(
            model=generation.model,
            fallback_models=generation.fallback_models,
            api_key=generation.api_key,
            project=generation.project,
            location=generation.location,
            temperature=generation.temperature,
            thinking_budget=generation.thinking_budget,
            api_version=generation.api_version or "v1",
            timeout_ms=generation.timeout_ms,
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    if generation.provider == "openai":
        return OpenAIGenerationProvider(
            model=generation.model or Defaults.OPENAI_GENERATION_MODEL,
            api_key=generation.api_key,
            url=generation.url or Defaults.OPENAI_RESPONSES_URL,
            timeout_seconds=generation.timeout_ms / 1000,
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    if generation.provider == "openai_compatible":
        if generation.urls:
            return OpenAICompatibleGenerationProviderPool(
                model=generation.model,
                api_key=generation.api_key,
                urls=generation.urls,
                timeout_seconds=generation.timeout_ms / 1000,
                max_tokens=generation.max_tokens,
                response_format=generation.response_format,
                extra_body=generation.extra_body,
                retry_attempts=generation.retry_attempts,
                retry_base_delay_seconds=generation.retry_base_delay_seconds,
                retry_max_delay_seconds=generation.retry_max_delay_seconds,
            )
        return OpenAICompatibleGenerationProvider(
            model=generation.model,
            api_key=generation.api_key,
            url=generation.url,
            timeout_seconds=generation.timeout_ms / 1000,
            max_tokens=generation.max_tokens,
            response_format=generation.response_format,
            extra_body=generation.extra_body,
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    raise ValueError(f"Unknown generation provider: {generation.provider}")


def _extra_args(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise ValueError(
        "generation.extra_body.extra_args must be a string or list of strings"
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return bool(value)
