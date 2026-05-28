from __future__ import annotations

from ..config import AppConfig
from ..settings import Defaults
from .generation_provider import GenerationProvider
from .gemini_generation_provider import GeminiGenerationProvider
from .openai_compatible_generation_provider import OpenAICompatibleGenerationProvider
from .openai_generation_provider import OpenAIGenerationProvider


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
        )
    if generation.provider == "openai":
        return OpenAIGenerationProvider(
            model=generation.model or Defaults.OPENAI_GENERATION_MODEL,
            api_key=generation.api_key,
            url=generation.url or Defaults.OPENAI_RESPONSES_URL,
        )
    if generation.provider == "openai_compatible":
        return OpenAICompatibleGenerationProvider(
            model=generation.model,
            api_key=generation.api_key,
            url=generation.url,
        )
    raise ValueError(f"Unknown generation provider: {generation.provider}")
