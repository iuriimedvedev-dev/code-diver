from __future__ import annotations

import os

from ..settings import Defaults, EnvironmentVariable
from .generation_result import GenerationResult
from .transient_generation_retry import TransientGenerationRetry


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
        retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
    ):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install dependencies with `uv sync` before using Gemini generation.") from exc

        self.name = "gemini"
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
        config = self._make_generation_config(response_mime_type=True, thinking=True)
        try:
            response = self._call_generate_content(model, prompt, config)
        except Exception as exc:
            if not self._is_unsupported_generation_config_error(exc):
                raise
            config = self._make_generation_config(response_mime_type=False, thinking=False)
            response = self._call_generate_content(model, prompt, config)
        return self._generation_result_from_response(model, response)

    def _make_generation_config(self, *, response_mime_type: bool, thinking: bool):
        config_kwargs = {"temperature": self.temperature}
        if response_mime_type:
            config_kwargs["response_mime_type"] = "application/json"
        if thinking and self.thinking_budget is not None:
            config_kwargs["thinking_config"] = self.types.ThinkingConfig(thinking_budget=self.thinking_budget)
        return self.types.GenerateContentConfig(**config_kwargs)

    def _call_generate_content(self, model: str, prompt: str, config):
        return self.retry.run(
            lambda: self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        )

    def _is_unsupported_generation_config_error(self, exc: Exception) -> bool:
        message = str(exc)
        return (
            "responseMimeType" in message
            or "response_mime_type" in message
            or "thinkingConfig" in message
            or "thinking_config" in message
        ) and ("INVALID_ARGUMENT" in message or "400" in message)

    def _generation_result_from_response(self, model: str, response) -> GenerationResult:
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
