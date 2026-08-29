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
    symbol_body: bool = Defaults.SYMBOL_BODY
    file_summary_chunks: bool = Defaults.FILE_SUMMARY_CHUNKS
    file_summary_head_line_max_chars: int = Defaults.FILE_SUMMARY_HEAD_LINE_MAX_CHARS
    file_summary_head_block_max_chars: int = Defaults.FILE_SUMMARY_HEAD_BLOCK_MAX_CHARS
    file_manifest_chunks: bool = Defaults.FILE_MANIFEST_CHUNKS
    file_api_manifest_chunks: bool = Defaults.FILE_API_MANIFEST_CHUNKS
    file_body_evidence_chunks: bool = Defaults.FILE_BODY_EVIDENCE_CHUNKS
    file_purpose_chunks: bool = Defaults.FILE_PURPOSE_CHUNKS
    documentation_summary_chunks: bool = Defaults.DOCUMENTATION_SUMMARY_CHUNKS
    documentation_manifest_chunks: bool = Defaults.DOCUMENTATION_MANIFEST_CHUNKS
    documentation_chunk_chunks: bool = Defaults.DOCUMENTATION_CHUNK_CHUNKS
    max_symbols_per_file: int | None = Defaults.MAX_SYMBOLS_PER_FILE
