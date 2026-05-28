from __future__ import annotations

import os

from ..settings import Defaults, EnvironmentVariable


class GeminiGenerationProvider:
    def __init__(
        self,
        model: str = Defaults.GENERATION_MODEL,
        api_key: str | None = None,
        temperature: float = Defaults.GENERATION_TEMPERATURE,
        thinking_budget: int | None = Defaults.GENERATION_THINKING_BUDGET,
    ):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install dependencies with `uv sync` before using Gemini generation.") from exc

        self.name = Defaults.GENERATION_PROVIDER
        self.model = model
        self.temperature = temperature
        self.thinking_budget = thinking_budget
        resolved_key = api_key or os.environ.get(EnvironmentVariable.GEMINI_API_KEY.value)
        self.client = genai.Client(api_key=resolved_key) if resolved_key else genai.Client()
        self.types = types

    def generate_json(self, prompt: str) -> str:
        config_kwargs = {
            "temperature": self.temperature,
            "response_mime_type": "application/json",
        }
        if self.thinking_budget is not None:
            config_kwargs["thinking_config"] = self.types.ThinkingConfig(thinking_budget=self.thinking_budget)
        config = self.types.GenerateContentConfig(**config_kwargs)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty indexing response.")
        return str(text)
