from __future__ import annotations

import os

from ..settings import Defaults, EnvironmentVariable
from .gemini_generation_provider import GeminiGenerationProvider
from .transient_generation_retry import TransientGenerationRetry


class VertexGenerationProvider(GeminiGenerationProvider):
    def __init__(
        self,
        model: str = Defaults.GENERATION_MODEL,
        fallback_models: list[str] | None = None,
        api_key: str | None = None,
        project: str | None = None,
        location: str | None = None,
        temperature: float = Defaults.GENERATION_TEMPERATURE,
        thinking_budget: int | None = Defaults.GENERATION_THINKING_BUDGET,
        api_version: str | None = "v1",
        timeout_ms: int = Defaults.GENERATION_TIMEOUT_MS,
        retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
    ):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install dependencies with `uv sync` before using Vertex generation.") from exc

        self.name = Defaults.VERTEX_PROVIDER
        self.model = model
        self.fallback_models = fallback_models or []
        self.temperature = temperature
        self.thinking_budget = thinking_budget
        self.timeout_ms = timeout_ms
        self.retry = TransientGenerationRetry(
            attempts=retry_attempts,
            base_delay_seconds=retry_base_delay_seconds,
            max_delay_seconds=retry_max_delay_seconds,
        )
        self.project = project or os.environ.get(EnvironmentVariable.GOOGLE_CLOUD_PROJECT.value)
        self.location = (
            location
            or os.environ.get(EnvironmentVariable.GOOGLE_CLOUD_LOCATION.value)
            or Defaults.VERTEX_LOCATION
        )
        http_options = types.HttpOptions(api_version=api_version, timeout=timeout_ms)
        client_kwargs = {
            "vertexai": True,
            "http_options": http_options,
        }
        if api_key:
            client_kwargs["api_key"] = api_key
        else:
            client_kwargs["project"] = self.project
            client_kwargs["location"] = self.location
        self.client = genai.Client(**client_kwargs)
        self.types = types
