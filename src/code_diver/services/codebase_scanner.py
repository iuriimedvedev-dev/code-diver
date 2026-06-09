from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..domain import CodeItem, CodeItemIndexKind, CodeItemMetadata, CodeSymbol
from .code_symbol_extractor import CodeSymbolExtractor
from .documentation_manifest_item_builder import DocumentationManifestItemBuilder
from .documentation_metadata_extractor import DocumentationMetadataExtractor
from .documentation_summary_item_builder import DocumentationSummaryItemBuilder
from .file_api_manifest_item_builder import FileApiManifestItemBuilder
from .file_body_evidence_item_builder import FileBodyEvidenceItemBuilder
from .file_manifest_item_builder import FileManifestItemBuilder
from .file_summary_item_builder import FileSummaryItemBuilder
from .structural_code_chunker import StructuralCodeChunker

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
    ".mdx",
    ".php",
    ".py",
    ".rb",
    ".rst",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".adoc",
    ".yaml",
    ".yml",
}


class CodebaseScanner:
    def __init__(
        self,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        line_chunks: bool = True,
        chunk_lines: int = 120,
        structural_chunks: bool = False,
        symbol_chunks: bool = False,
        symbol_body: bool = True,
        file_summary_chunks: bool = False,
        file_manifest_chunks: bool = False,
        file_api_manifest_chunks: bool = False,
        file_body_evidence_chunks: bool = False,
        documentation_summary_chunks: bool = False,
        documentation_manifest_chunks: bool = False,
        max_symbols_per_file: int | None = None,
        symbol_extractor: CodeSymbolExtractor | None = None,
        file_summary_builder: FileSummaryItemBuilder | None = None,
        file_manifest_builder: FileManifestItemBuilder | None = None,
        file_api_manifest_builder: FileApiManifestItemBuilder | None = None,
        file_body_evidence_builder: FileBodyEvidenceItemBuilder | None = None,
        documentation_summary_builder: DocumentationSummaryItemBuilder | None = None,
        documentation_manifest_builder: DocumentationManifestItemBuilder | None = None,
        documentation_extractor: DocumentationMetadataExtractor | None = None,
        structural_chunker: StructuralCodeChunker | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ):
        self.include = include or []
        self.exclude = [*DEFAULT_EXCLUDES, *(exclude or [])]
        self.max_file_bytes = max_file_bytes
        self.line_chunks = line_chunks
        self.chunk_lines = chunk_lines
        self.structural_chunks = structural_chunks
        self.symbol_chunks = symbol_chunks
        self.symbol_body = symbol_body
        self.file_summary_chunks = file_summary_chunks
        self.file_manifest_chunks = file_manifest_chunks
        self.file_api_manifest_chunks = file_api_manifest_chunks
        self.file_body_evidence_chunks = file_body_evidence_chunks
        self.documentation_summary_chunks = documentation_summary_chunks
        self.documentation_manifest_chunks = documentation_manifest_chunks
        self.max_symbols_per_file = max_symbols_per_file
        self.symbol_extractor = symbol_extractor or CodeSymbolExtractor()
        self.file_summary_builder = file_summary_builder or FileSummaryItemBuilder()
        self.file_manifest_builder = file_manifest_builder or FileManifestItemBuilder()
        self.file_api_manifest_builder = file_api_manifest_builder or FileApiManifestItemBuilder()
        self.file_body_evidence_builder = file_body_evidence_builder or FileBodyEvidenceItemBuilder()
        self.documentation_extractor = documentation_extractor or DocumentationMetadataExtractor()
        self.documentation_summary_builder = (
            documentation_summary_builder
            or DocumentationSummaryItemBuilder(self.documentation_extractor)
        )
        self.documentation_manifest_builder = (
            documentation_manifest_builder
            or DocumentationManifestItemBuilder(self.documentation_extractor)
        )
        self.structural_chunker = structural_chunker or StructuralCodeChunker(chunk_lines, self.symbol_extractor)
        self.progress_callback = progress_callback

    def scan(self, root: Path) -> list[CodeItem]:
        root = root.resolve()
        items: list[CodeItem] = []
        processed_files = 0
        for path, rel_path in self._candidate_files(root):
            text = self._read_text(path)
            if text is None or not text.strip():
                continue
            processed_files += 1
            items.extend(self._items_for_file(rel_path, text))
            if self.progress_callback:
                self.progress_callback(processed_files, len(items))
        return items

    def count_candidate_files(self, root: Path) -> int:
        root = root.resolve()
        return sum(1 for _ in self._candidate_files(root))

    def _candidate_files(self, root: Path):
        yield from self._rg_candidate_files(root) or self._walk_candidate_files(root)

    def _rg_candidate_files(self, root: Path) -> list[tuple[Path, str]]:
        if shutil.which("rg") is None:
            return []
        try:
            result = subprocess.run(
                ["rg", "--files", "--color", "never", "--no-require-git"],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            )
        except OSError:
            return []
        if result.returncode not in {0, 1}:
            return []
        candidates: list[tuple[Path, str]] = []
        for rel_path in sorted(line.strip() for line in result.stdout.splitlines() if line.strip()):
            path = root / rel_path
            if not self._should_skip_file(path, rel_path):
                candidates.append((path, rel_path))
        return candidates

    def _walk_candidate_files(self, root: Path) -> list[tuple[Path, str]]:
        candidates: list[tuple[Path, str]] = []
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
                if not self._should_skip_file(path, rel_path):
                    candidates.append((path, rel_path))
        return candidates

    def _items_for_file(self, rel_path: str, text: str) -> list[CodeItem]:
        if self._uses_documentation_lane(rel_path):
            return self._documentation_items(rel_path, text)
        symbols = (
            self._symbols_for_file(rel_path, text)
            if (
                self.symbol_chunks
                or self.file_summary_chunks
                or self.file_manifest_chunks
                or self.file_api_manifest_chunks
                or self.file_body_evidence_chunks
            )
            else []
        )
        items = self._chunk_file(rel_path, text) if self.line_chunks else []
        if self.symbol_chunks:
            items.extend(self._symbol_items(rel_path, text, symbols))
        if self.file_summary_chunks:
            items.append(self.file_summary_builder.build(rel_path, text, symbols))
        if self.file_manifest_chunks:
            items.append(self.file_manifest_builder.build(rel_path, text, symbols))
        if self.file_api_manifest_chunks:
            items.append(self.file_api_manifest_builder.build(rel_path, text, symbols))
        if self.file_body_evidence_chunks:
            items.append(self.file_body_evidence_builder.build(rel_path, text, symbols))
        return items

    def _uses_documentation_lane(self, rel_path: str) -> bool:
        return (
            (self.documentation_summary_chunks or self.documentation_manifest_chunks)
            and self.documentation_extractor.is_documentation_path(rel_path)
        )

    def _documentation_items(self, rel_path: str, text: str) -> list[CodeItem]:
        items = self._chunk_file(rel_path, text) if self.line_chunks else []
        if self.documentation_summary_chunks:
            items.append(self.documentation_summary_builder.build(rel_path, text))
        if self.documentation_manifest_chunks:
            items.append(self.documentation_manifest_builder.build(rel_path, text))
        return items

    def _symbols_for_file(self, rel_path: str, text: str) -> list[CodeSymbol]:
        symbols = self.symbol_extractor.extract(rel_path, text)
        if self.max_symbols_per_file is None or self.max_symbols_per_file < 0:
            return symbols
        return symbols[: self.max_symbols_per_file]

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
        line_chunks = self._line_chunks(rel_path, text)
        if self.structural_chunks:
            structural_items = self.structural_chunker.chunk(rel_path, text)
            if structural_items:
                return [*line_chunks, *structural_items]
        return line_chunks

    def _line_chunks(self, rel_path: str, text: str) -> list[CodeItem]:
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
            content_lines = [
                f"symbol: {symbol.kind} {symbol.name}",
                f"signature: {symbol.signature}",
                f"lines: {start_line}-{end_line}",
            ]
            if self.symbol_body:
                content_lines.extend(["", body])
            items.append(
                CodeItem(
                    id=f"{rel_path}::{symbol.name}#{digest}",
                    path=rel_path,
                    title=f"{rel_path}::{symbol.name}",
                    content="\n".join(content_lines),
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
