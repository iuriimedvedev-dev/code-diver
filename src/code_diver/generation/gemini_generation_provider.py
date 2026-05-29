from __future__ import annotations

import os

from ..settings import Defaults, EnvironmentVariable
from .generation_result import GenerationResult


class GeminiGenerationProvider:
    def __init__(
        self,
        model: str = Defaults.GENERATION_MODEL,
        fallback_models: list[str] | None = None,
        api_key: str | None = None,
        temperature: float = Defaults.GENERATION_TEMPERATURE,
        thinking_budget: int | None = Defaults.GENERATION_THINKING_BUDGET,
        api_version: str | None = Defaults.GENERATION_API_VERSION,
        timeout_ms: int = Defaults.GENERATION_TIMEOUT_MS,
    ):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install dependencies with `uv sync` before using Gemini generation.") from exc

        self.name = Defaults.GENERATION_PROVIDER
        self.model = model
        self.fallback_models = fallback_models or []
        self.temperature = temperature
        self.thinking_budget = thinking_budget
        self.timeout_ms = timeout_ms
        resolved_key = api_key or os.environ.get(EnvironmentVariable.GEMINI_API_KEY.value)
        http_options = types.HttpOptions(api_version=api_version, timeout=timeout_ms)
        client_kwargs = {"http_options": http_options}
        if resolved_key:
            client_kwargs["api_key"] = resolved_key
        self.client = genai.Client(**client_kwargs)
        self.types = types

    def generate_json(self, prompt: str) -> str:
        return self.generate_json_result(prompt).text

    def generate_json_result(self, prompt: str) -> GenerationResult:
        errors: list[str] = []
        for model in [self.model, *self.fallback_models]:
            try:
                return self._generate_json(model, prompt)
            except Exception as exc:
                errors.append(f"{model}: {exc}")
        raise RuntimeError("Gemini generation failed for all configured models: " + " | ".join(errors))

    def _generate_json(self, model: str, prompt: str) -> GenerationResult:
        config_kwargs = {
            "temperature": self.temperature,
            "response_mime_type": "application/json",
        }
        if self.thinking_budget is not None:
            config_kwargs["thinking_config"] = self.types.ThinkingConfig(thinking_budget=self.thinking_budget)
        config = self.types.GenerateContentConfig(**config_kwargs)
        response = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty indexing response.")
        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(
            getattr(usage, "prompt_token_count", 0)
            or getattr(usage, "input_token_count", 0)
            or 0
        )
        output_tokens = int(
            getattr(usage, "candidates_token_count", 0)
            or getattr(usage, "output_token_count", 0)
            or 0
        )
        total_tokens = int(getattr(usage, "total_token_count", 0) or input_tokens + output_tokens)
        return GenerationResult(
            text=str(text),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
