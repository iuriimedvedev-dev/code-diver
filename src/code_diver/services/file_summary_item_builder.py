from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol

IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import\s+.+|import\s+[\w.,\s]+)\s*$")

TRUNCATION_MARKER = " ...[truncated]"


class FileSummaryItemBuilder:
    def __init__(
        self,
        max_imports: int = 24,
        max_symbols: int = 80,
        max_head_lines: int = 24,
        max_head_line_chars: int = 200,
        max_head_block_chars: int = 4000,
    ):
        self.max_imports = max_imports
        self.max_symbols = max_symbols
        self.max_head_lines = max_head_lines
        self.max_head_line_chars = max_head_line_chars
        self.max_head_block_chars = max_head_block_chars

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> CodeItem:
        digest = hashlib.sha1(f"{rel_path}:file-summary".encode()).hexdigest()[:12]
        content = "\n".join(
            [
                f"file: {rel_path}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._head_section(text),
                self._symbols_section(symbols),
                self._imports_section(text),
            ]
        ).strip()
        return CodeItem(
            id=f"{rel_path}::file_summary#{digest}",
            path=rel_path,
            title=f"{rel_path}::file_summary",
            content=content,
            metadata={
                CodeItemMetadata.SOURCE: "scanner",
                CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.FILE_SUMMARY,
            },
        )

    def _imports_section(self, text: str) -> str:
        imports = [line.strip() for line in text.splitlines() if IMPORT_RE.match(line)]
        if not imports:
            return "imports: none"
        rows = imports[: self.max_imports]
        return "imports:\n" + "\n".join(f"- {row}" for row in rows)

    def _symbols_section(self, symbols: list[CodeSymbol]) -> str:
        if not symbols:
            return "symbols: none"
        rows = [
            f"- {symbol.kind} {symbol.name}: {symbol.signature}"
            for symbol in symbols[: self.max_symbols]
        ]
        return "symbols:\n" + "\n".join(rows)

    def _head_section(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return "head: empty"
        rows = [self._cap_line(row) for row in lines[: self.max_head_lines]]
        block = "head:\n" + "\n".join(f"- {row}" for row in rows)
        return self._cap_block(block)

    def _cap_line(self, line: str) -> str:
        if len(line) <= self.max_head_line_chars:
            return line
        return line[: self.max_head_line_chars] + TRUNCATION_MARKER

    def _cap_block(self, block: str) -> str:
        if len(block) <= self.max_head_block_chars:
            return block
        limit = max(self.max_head_block_chars - len(TRUNCATION_MARKER), 0)
        return block[:limit] + TRUNCATION_MARKER
