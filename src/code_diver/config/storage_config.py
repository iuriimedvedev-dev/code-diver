from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults
from .qdrant_config import QdrantConfig


@dataclass(slots=True)
class StorageConfig:
    provider: str = Defaults.STORAGE_PROVIDER
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
