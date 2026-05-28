from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class QdrantConfig:
    url: str = Defaults.QDRANT_URL
    location: str | None = None
    collection: str = Defaults.QDRANT_COLLECTION
    api_key: str | None = None
    api_key_env: str | None = Defaults.QDRANT_API_KEY_ENV
    batch_size: int = Defaults.QDRANT_BATCH_SIZE
