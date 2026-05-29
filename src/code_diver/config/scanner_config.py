from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class ScannerConfig:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    max_file_bytes: int = Defaults.MAX_FILE_BYTES
    chunk_lines: int = Defaults.CHUNK_LINES
    symbol_chunks: bool = Defaults.SYMBOL_CHUNKS
