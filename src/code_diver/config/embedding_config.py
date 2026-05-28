from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class EmbeddingConfig:
    provider: str = Defaults.EMBEDDING_PROVIDER
    model: str | None = Defaults.EMBEDDING_MODEL
    dimensions: int | None = Defaults.EMBEDDING_DIMENSIONS
    api_key: str | None = None
    url: str | None = None
    batch_size: int = Defaults.EMBEDDING_BATCH_SIZE
    retry_attempts: int = Defaults.EMBEDDING_RETRY_ATTEMPTS
    retry_delay_seconds: float = Defaults.EMBEDDING_RETRY_DELAY_SECONDS
