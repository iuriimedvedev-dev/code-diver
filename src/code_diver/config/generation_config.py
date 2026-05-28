from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class GenerationConfig:
    provider: str = Defaults.GENERATION_PROVIDER
    model: str = Defaults.GENERATION_MODEL
    api_key: str | None = None
    temperature: float = Defaults.GENERATION_TEMPERATURE
    thinking_budget: int | None = Defaults.GENERATION_THINKING_BUDGET
