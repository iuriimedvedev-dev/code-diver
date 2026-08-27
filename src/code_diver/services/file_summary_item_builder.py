from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol

LICENSE_OR_COPYRIGHT_RE = re.compile(
    r"^\s*(//|#|%|;)\s*[Cc]opyright|^\s*/\*(?!\*)|^\s*\*[^/]|^[-]{20,}"
)

IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import\s+.+|import\s+[\w.,\s;]+)\s*$")
PACKAGE_RE = re.compile(r"^\s*package\s+[\w.]+")
FILE_ANNOTATION_RE = re.compile(r"^\s*@file:\s*")

TRUNCATION_MARKER = " ...[truncated]"


class FileSummaryItemBuilder:
    def __init__(
        self,
        max_imports: int = 24,
        max_symbols: int = 80,
        max_head_lines: int = 24,
        max_head_line_chars: int = 200,
        max_head_block_chars: int = 4000,
        max_head_import_lines: int = 5,
    ):
        self.max_imports = max_imports
        self.max_symbols = max_symbols
        self.max_head_lines = max_head_lines
        self.max_head_line_chars = max_head_line_chars
        self.max_head_block_chars = max_head_block_chars
        self.max_head_import_lines = max_head_import_lines

    def build(self, rel_path: str, text: str, symbols: list[CodeSymbol]) -> CodeItem:
        digest = hashlib.sha1(f"{rel_path}:file-summary".encode()).hexdigest()[:12]
        content = "\n".join(
            [
                f"file: {rel_path}",
                f"extension: {Path(rel_path).suffix.lower()}",
                self._symbols_section(symbols),
                self._head_section(text),
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
        """Return the most informative head lines of the source file.

        Skips license headers, copyright boilerplate, and `@file:` annotations.
        Package declarations are kept — they provide useful module/layer signal.
        Import statements are capped at `max_head_import_lines` (default 5) to
        prevent them from dominating the head section. Returns the first
        meaningful lines: class/interface/object/enum declarations,
        KDoc/Javadoc blocks, annotations, and field/method signatures.
        """
        meaningful = self._skip_boilerplate(text)
        if not meaningful:
            return "head: empty"
        rows = [self._cap_line(row) for row in meaningful[: self.max_head_lines]]
        block = "head:\n" + "\n".join(f"- {row}" for row in rows)
        return self._cap_block(block)

    @staticmethod
    def _is_boilerplate(line: str) -> bool:
        """Return True if the line is purely legal/formatting boilerplate.

        Only copyright/license headers and @file annotations are skipped.
        Package declarations and code lines are preserved.
        Import statements are handled separately by `_skip_boilerplate`
        with a cap on the number of imported lines.
        """
        stripped = line.strip()
        if not stripped:
            return True
        if LICENSE_OR_COPYRIGHT_RE.search(stripped):
            return True
        if FILE_ANNOTATION_RE.match(stripped):
            return True
        return False

    def _skip_boilerplate(self, text: str) -> list[str]:
        """Return non-boilerplate lines, preserving relative order, up to max_head_lines.

        Skips only copyright/license headers and @file annotations.
        Package declarations and code lines are preserved.
        Import statements are capped at `max_head_import_lines` to prevent
        the head section from being consumed entirely by imports.
        Also includes any KDoc/Javadoc block that appears before the first
        meaningful line, so class-level doc is not lost.
        """
        lines = text.splitlines()
        kdoc_lines: list[str] = []
        meaningful: list[str] = []
        import_count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if self._is_boilerplate(stripped):
                if stripped.startswith("/**") or stripped.startswith("*"):
                    kdoc_lines.append(stripped)
                continue
            # Cap import lines to prevent them from dominating the head section
            if IMPORT_RE.match(stripped):
                if import_count < self.max_head_import_lines:
                    import_count += 1
                    if not meaningful and kdoc_lines:
                        meaningful.extend(kdoc_lines[:4])
                        kdoc_lines.clear()
                    meaningful.append(stripped)
                continue
            # First non-boilerplate, non-import line — flush KDoc
            if not meaningful and kdoc_lines:
                meaningful.extend(kdoc_lines[:4])
                kdoc_lines.clear()
            meaningful.append(stripped)
            if len(meaningful) >= self.max_head_lines:
                break
        if not meaningful and kdoc_lines:
            meaningful = kdoc_lines[: self.max_head_lines]
        return meaningful

    def _cap_line(self, line: str) -> str:
        if len(line) <= self.max_head_line_chars:
            return line
        return line[: self.max_head_line_chars] + TRUNCATION_MARKER

    def _cap_block(self, block: str) -> str:
        if len(block) <= self.max_head_block_chars:
            return block
        limit = max(self.max_head_block_chars - len(TRUNCATION_MARKER), 0)
        return block[:limit] + TRUNCATION_MARKER
