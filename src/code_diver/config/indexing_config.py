from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults
from .ai_index_config import AiIndexConfig


@dataclass(slots=True)
class IndexingConfig:
    mode: str = Defaults.INDEXING_MODE
    ai: AiIndexConfig = field(default_factory=AiIndexConfig)
