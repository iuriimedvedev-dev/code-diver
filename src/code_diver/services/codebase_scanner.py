from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol
from .code_symbol_extractor import CodeSymbolExtractor
from .file_summary_item_builder import FileSummaryItemBuilder

DEFAULT_EXCLUDES = (
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".code-diver/**",
    ".pi/npm/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "target/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "uv.lock",
)

DEFAULT_INCLUDE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".kt",
    ".kts",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


class CodebaseScanner:
    def __init__(
        self,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        chunk_lines: int = 120,
        symbol_chunks: bool = False,
        file_summary_chunks: bool = False,
        symbol_extractor: CodeSymbolExtractor | None = None,
        file_summary_builder: FileSummaryItemBuilder | None = None,
    ):
        self.include = include or []
        self.exclude = [*DEFAULT_EXCLUDES, *(exclude or [])]
        self.max_file_bytes = max_file_bytes
        self.chunk_lines = chunk_lines
        self.symbol_chunks = symbol_chunks
        self.file_summary_chunks = file_summary_chunks
        self.symbol_extractor = symbol_extractor or CodeSymbolExtractor()
        self.file_summary_builder = file_summary_builder or FileSummaryItemBuilder()

    def scan(self, root: Path) -> list[CodeItem]:
        root = root.resolve()
        items: list[CodeItem] = []
        for current_root, dir_names, file_names in os.walk(root):
            current_path = Path(current_root)
            dir_names[:] = [
                name
                for name in sorted(dir_names)
                if not self._matches_excluded_directory((current_path / name).relative_to(root).as_posix())
            ]
            for file_name in sorted(file_names):
                path = current_path / file_name
                rel_path = path.relative_to(root).as_posix()
                if self._should_skip_file(path, rel_path):
                    continue
                text = self._read_text(path)
                if text is None or not text.strip():
                    continue
                items.extend(self._items_for_file(rel_path, text))
        return items

    def _items_for_file(self, rel_path: str, text: str) -> list[CodeItem]:
        symbols = self.symbol_extractor.extract(rel_path, text) if self.symbol_chunks or self.file_summary_chunks else []
        items = self._chunk_file(rel_path, text)
        if self.symbol_chunks:
            items.extend(self._symbol_items(rel_path, text, symbols))
        if self.file_summary_chunks:
            items.append(self.file_summary_builder.build(rel_path, text, symbols))
        return items

    def _should_skip_file(self, path: Path, rel_path: str) -> bool:
        if self._matches_any(rel_path, self.exclude):
            return True
        if self.include and not self._matches_any(rel_path, self.include):
            return True
        if not self.include and path.suffix.lower() not in DEFAULT_INCLUDE_SUFFIXES:
            return True
        return False

    def _matches_excluded_directory(self, rel_path: str) -> bool:
        return any(self._matches_directory_pattern(rel_path, pattern) for pattern in self.exclude)

    def _matches_directory_pattern(self, rel_path: str, pattern: str) -> bool:
        normalized = pattern.rstrip("/")
        if normalized.endswith("/**"):
            base = normalized[:-3]
            if "/" not in base and base in rel_path.split("/"):
                return True
            return rel_path == base or rel_path.startswith(base + "/")
        return self._matches_any(rel_path, [pattern])

    def _read_text(self, path: Path) -> str | None:
        try:
            if path.stat().st_size > self.max_file_bytes:
                return None
            raw = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in raw:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")

    def _chunk_file(self, rel_path: str, text: str) -> list[CodeItem]:
        lines = text.splitlines()
        chunks: list[CodeItem] = []
        for offset in range(0, len(lines), self.chunk_lines):
            chunk = lines[offset : offset + self.chunk_lines]
            start_line = offset + 1
            end_line = offset + len(chunk)
            title = rel_path if len(lines) <= self.chunk_lines else f"{rel_path}:{start_line}-{end_line}"
            digest = hashlib.sha1(f"{rel_path}:{start_line}:{end_line}".encode("utf-8")).hexdigest()[:12]
            chunks.append(
                CodeItem(
                    id=f"{rel_path}#{digest}",
                    path=rel_path,
                    title=title,
                    content="\n".join(chunk),
                    start_line=start_line,
                    end_line=end_line,
                    metadata={
                        CodeItemMetadata.SOURCE: "scanner",
                        CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.CHUNK,
                    },
                )
            )
        return chunks

    def _symbol_items(self, rel_path: str, text: str, symbols: list[CodeSymbol] | None = None) -> list[CodeItem]:
        lines = text.splitlines()
        items: list[CodeItem] = []
        for symbol in symbols if symbols is not None else self.symbol_extractor.extract(rel_path, text):
            start_line = max(symbol.start_line, 1)
            end_line = min(max(symbol.end_line, start_line), len(lines))
            body = "\n".join(lines[start_line - 1 : end_line])
            digest = hashlib.sha1(f"{rel_path}:{symbol.name}:{start_line}:{end_line}".encode("utf-8")).hexdigest()[:12]
            items.append(
                CodeItem(
                    id=f"{rel_path}::{symbol.name}#{digest}",
                    path=rel_path,
                    title=f"{rel_path}::{symbol.name}",
                    content="\n".join(
                        [
                            f"symbol: {symbol.kind} {symbol.name}",
                            f"signature: {symbol.signature}",
                            "",
                            body,
                        ]
                    ),
                    start_line=start_line,
                    end_line=end_line,
                    metadata={
                        CodeItemMetadata.SOURCE: "scanner",
                        CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.SYMBOL,
                        CodeItemMetadata.KIND: symbol.kind,
                        CodeItemMetadata.SYMBOL: symbol.name,
                    },
                )
            )
        return items

    def _matches_any(self, rel_path: str, patterns: list[str]) -> bool:
        return any(
            fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(f"./{rel_path}", pattern)
            for pattern in patterns
        )
