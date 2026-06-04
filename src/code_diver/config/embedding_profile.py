from __future__ import annotations

from dataclasses import dataclass

from .embedding_config import EmbeddingConfig


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    key: str
    label: str
    description: str
    config: EmbeddingConfig
    startup_hint: str | None = None

