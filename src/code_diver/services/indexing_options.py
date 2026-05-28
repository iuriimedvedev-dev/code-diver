from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class IndexingOptions:
    embedding_batch_size: int = Defaults.EMBEDDING_BATCH_SIZE
    embedding_workers: int = Defaults.EMBEDDING_WORKERS
    embedding_max_input_chars: int | None = Defaults.EMBEDDING_MAX_INPUT_CHARS
    progress: bool = Defaults.INDEXING_PROGRESS
