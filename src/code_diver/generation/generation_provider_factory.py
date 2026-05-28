from __future__ import annotations

from ..config import AppConfig
from ..settings import Defaults
from .generation_provider import GenerationProvider
from .gemini_generation_provider import GeminiGenerationProvider


def create_generation_provider(config: AppConfig) -> GenerationProvider:
    generation = config.generation
    if generation.provider == Defaults.GENERATION_PROVIDER:
        return GeminiGenerationProvider(
            model=generation.model,
            api_key=generation.api_key,
            temperature=generation.temperature,
            thinking_budget=generation.thinking_budget,
        )
    raise ValueError(f"Unknown generation provider: {generation.provider}")
