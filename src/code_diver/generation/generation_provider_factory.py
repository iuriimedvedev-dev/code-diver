from __future__ import annotations

from ..config import AppConfig
from ..settings import Defaults
from .generation_provider import GenerationProvider
from .gemini_generation_provider import GeminiGenerationProvider
from .openai_compatible_generation_provider import OpenAICompatibleGenerationProvider
from .openai_generation_provider import OpenAIGenerationProvider
from .vertex_generation_provider import VertexGenerationProvider


def create_generation_provider(config: AppConfig) -> GenerationProvider:
    generation = config.generation
    if generation.provider == Defaults.GENERATION_PROVIDER:
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
        return OpenAICompatibleGenerationProvider(
            model=generation.model,
            api_key=generation.api_key,
            url=generation.url,
            timeout_seconds=generation.timeout_ms / 1000,
            max_tokens=generation.max_tokens,
            response_format=generation.response_format,
            retry_attempts=generation.retry_attempts,
            retry_base_delay_seconds=generation.retry_base_delay_seconds,
            retry_max_delay_seconds=generation.retry_max_delay_seconds,
        )
    raise ValueError(f"Unknown generation provider: {generation.provider}")
