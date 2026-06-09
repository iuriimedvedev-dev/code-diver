from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class GenerationConfig:
    provider: str = Defaults.GENERATION_PROVIDER
    model: str = Defaults.GENERATION_MODEL
    fallback_models: list[str] = field(default_factory=lambda: list(Defaults.GENERATION_FALLBACK_MODELS))
    api_key: str | None = None
    project: str | None = None
    location: str | None = None
    url: str | None = None
    urls: list[str] = field(default_factory=list)
    temperature: float = Defaults.GENERATION_TEMPERATURE
    thinking_budget: int | None = Defaults.GENERATION_THINKING_BUDGET
    api_version: str | None = Defaults.GENERATION_API_VERSION
    timeout_ms: int = Defaults.GENERATION_TIMEOUT_MS
    max_tokens: int | None = Defaults.GENERATION_MAX_TOKENS
    response_format: bool | str | dict[str, object] = True
    extra_body: dict[str, object] = field(default_factory=dict)
    retry_attempts: int = Defaults.GENERATION_RETRY_ATTEMPTS
    retry_base_delay_seconds: float = Defaults.GENERATION_RETRY_BASE_DELAY_SECONDS
    retry_max_delay_seconds: float = Defaults.GENERATION_RETRY_MAX_DELAY_SECONDS
