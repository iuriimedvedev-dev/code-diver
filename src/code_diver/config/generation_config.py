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
    temperature: float = Defaults.GENERATION_TEMPERATURE
    thinking_budget: int | None = Defaults.GENERATION_THINKING_BUDGET
    api_version: str | None = Defaults.GENERATION_API_VERSION
    timeout_ms: int = Defaults.GENERATION_TIMEOUT_MS
