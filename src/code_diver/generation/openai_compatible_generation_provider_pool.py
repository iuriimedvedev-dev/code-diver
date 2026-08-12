from __future__ import annotations

from threading import Lock
from typing import Any

from ..settings import Defaults
from .generation_result import GenerationResult
from .openai_compatible_generation_provider import OpenAICompatibleGenerationProvider


class OpenAICompatibleGenerationProviderPool:
    def __init__(
        self,
        model: str,
        urls: list[str],
        api_key: str | None = None,
        timeout_seconds: float = Defaults.OPENAI_TIMEOUT_SECONDS,
        max_tokens: int | None = None,
        response_format: bool | str | dict[str, Any] = True,
        extra_body: dict[str, Any] | None = None,
        retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS,
        retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS,
        retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS,
    ):
        cleaned_urls = [url for url in (url.strip() for url in urls) if url]
        if not cleaned_urls:
            raise ValueError("OpenAI-compatible generation provider pool requires at least one URL.")
        self.name = "openai_compatible_pool"
        self.model = model
        self.providers = [
            OpenAICompatibleGenerationProvider(
                model=model,
                api_key=api_key,
                url=url,
                timeout_seconds=timeout_seconds,
                max_tokens=max_tokens,
                response_format=response_format,
                extra_body=extra_body,
                retry_attempts=retry_attempts,
                retry_base_delay_seconds=retry_base_delay_seconds,
                retry_max_delay_seconds=retry_max_delay_seconds,
            )
            for url in cleaned_urls
        ]
        self._lock = Lock()
        self._next_index = 0

    def generate_json(self, prompt: str, *, schema: dict[str, Any] | None = None) -> str:
        return self.generate_json_result(prompt, schema=schema).text

    def generate_json_result(self, prompt: str, *, schema: dict[str, Any] | None = None) -> GenerationResult:
        return self._next_provider().generate_json_result(prompt, schema=schema)

    def _next_provider(self) -> OpenAICompatibleGenerationProvider:
        with self._lock:
            provider = self.providers[self._next_index]
            self._next_index = (self._next_index + 1) % len(self.providers)
            return provider
