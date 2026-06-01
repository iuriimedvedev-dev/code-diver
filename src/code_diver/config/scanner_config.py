from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class ScannerConfig:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    max_file_bytes: int = Defaults.MAX_FILE_BYTES
    line_chunks: bool = Defaults.LINE_CHUNKS
    chunk_lines: int = Defaults.CHUNK_LINES
    structural_chunks: bool = Defaults.STRUCTURAL_CHUNKS
    symbol_chunks: bool = Defaults.SYMBOL_CHUNKS
    file_summary_chunks: bool = Defaults.FILE_SUMMARY_CHUNKS
    max_symbols_per_file: int | None = Defaults.MAX_SYMBOLS_PER_FILE
