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
from .file_purpose_item_builder import FilePurposeItemBuilder
from .file_manifest_item_builder import FileManifestItemBuilder
from .file_summary_item_builder import FileSummaryItemBuilder
from .structural_code_chunker import StructuralCodeChunker
from .symbol_chunk_item_builder import SymbolChunkItemBuilder

EXTRA_TEST_DIR_EXCLUDE_PATTERNS = ("**/testSrc/**", "**/testSources/**", "**/platform-tests/**")

DEFAULT_EXCLUDES = (
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".code-diver/**",
    ".pi/npm/**",
    # Wildcarded on purpose: a repo that needs two interpreters names the second one
    # `.venv-something`, and only `.venv` was excluded. Indexing this repo picked up
    # `.venv-vllm-metal-official` -- 21,413 indexable files, ~60x the real source tree --
    # which does not fail, it just buries the codebase under its own dependencies.
    # Exclude-pattern segments are fnmatch'd, so one wildcard covers every variant.
    ".venv*/**",
    "venv*/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "target/**",
    *EXTRA_TEST_DIR_EXCLUDE_PATTERNS,
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
        file_summary_head_line_max_chars: int = 200,
        file_summary_head_block_max_chars: int = 4000,
        file_summary_compact_budget: bool = False,
        file_summary_compact_path: bool | None = None,
        file_summary_term_stopwords: bool | None = None,
        file_manifest_chunks: bool = False,
        file_manifest_symbol_surface: bool = False,
        file_api_manifest_chunks: bool = False,
        file_body_evidence_chunks: bool = False,
        file_purpose_chunks: bool = False,
        symbol_chunk_chunks: bool = False,
        documentation_summary_chunks: bool = False,
        documentation_manifest_chunks: bool = False,
        documentation_chunk_chunks: bool = False,
        max_symbols_per_file: int | None = None,
        symbol_extractor: CodeSymbolExtractor | None = None,
        file_summary_builder: FileSummaryItemBuilder | None = None,
        file_manifest_builder: FileManifestItemBuilder | None = None,
        file_api_manifest_builder: FileApiManifestItemBuilder | None = None,
        file_body_evidence_builder: FileBodyEvidenceItemBuilder | None = None,
        file_purpose_builder: FilePurposeItemBuilder | None = None,
        symbol_chunk_builder: SymbolChunkItemBuilder | None = None,
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
        self.file_summary_head_line_max_chars = file_summary_head_line_max_chars
        self.file_summary_head_block_max_chars = file_summary_head_block_max_chars
        self.file_summary_compact_budget = file_summary_compact_budget
        self.file_summary_compact_path = file_summary_compact_path
        self.file_summary_term_stopwords = file_summary_term_stopwords
        self.file_manifest_chunks = file_manifest_chunks
        self.file_manifest_symbol_surface = file_manifest_symbol_surface
        self.file_api_manifest_chunks = file_api_manifest_chunks
        self.file_body_evidence_chunks = file_body_evidence_chunks
        self.file_purpose_chunks = file_purpose_chunks
        self.symbol_chunk_chunks = symbol_chunk_chunks
        self.documentation_summary_chunks = documentation_summary_chunks
        self.documentation_manifest_chunks = documentation_manifest_chunks
        self.documentation_chunk_chunks = documentation_chunk_chunks
        self.max_symbols_per_file = max_symbols_per_file
        self.symbol_extractor = symbol_extractor or CodeSymbolExtractor()
        self.file_summary_builder = file_summary_builder or FileSummaryItemBuilder(
            max_head_line_chars=file_summary_head_line_max_chars,
            max_head_block_chars=file_summary_head_block_max_chars,
            compact_budget=file_summary_compact_budget,
            compact_path=file_summary_compact_path,
            term_stopwords=file_summary_term_stopwords,
        )
        self.file_manifest_builder = file_manifest_builder or FileManifestItemBuilder(
            symbol_surface=file_manifest_symbol_surface,
        )
        self.file_api_manifest_builder = file_api_manifest_builder or FileApiManifestItemBuilder()
        self.file_body_evidence_builder = file_body_evidence_builder or FileBodyEvidenceItemBuilder()
        self.file_purpose_builder = file_purpose_builder or FilePurposeItemBuilder()
        self.symbol_chunk_builder = symbol_chunk_builder or SymbolChunkItemBuilder()
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
                if not self._is_excluded(
                    (current_path / name).relative_to(root).as_posix(), is_dir=True
                )
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
                or self.symbol_chunk_chunks
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
        if self.file_purpose_chunks:
            purpose_item = self.file_purpose_builder.build(rel_path, text, symbols)
            if purpose_item is not None:
                items.append(purpose_item)
        if self.symbol_chunk_chunks:
            items.extend(self.symbol_chunk_builder.build(rel_path, text, symbols))
        return items

    def _uses_documentation_lane(self, rel_path: str) -> bool:
        return (
            (
                self.documentation_summary_chunks
                or self.documentation_manifest_chunks
                or self.documentation_chunk_chunks
            )
            and self.documentation_extractor.is_documentation_path(rel_path)
        )

    def _documentation_items(self, rel_path: str, text: str) -> list[CodeItem]:
        items = self._documentation_chunks(rel_path, text) if self.documentation_chunk_chunks else []
        if self.line_chunks:
            items.extend(self._chunk_file(rel_path, text))
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
        if self._is_excluded(rel_path):
            return True
        if self.include and not self._matches_any(rel_path, self.include):
            return True
        return bool(not self.include and path.suffix.lower() not in DEFAULT_INCLUDE_SUFFIXES)

    def _is_excluded(self, rel_path: str, *, is_dir: bool = False) -> bool:
        """Single exclusion predicate shared by the rg and os.walk enumeration paths.

        A pattern ending in ``/**`` excludes the directory (and everything under
        it) at any depth, not just when it is rooted at ``rel_path``'s top level.
        Any other pattern (e.g. ``*.lock``, ``**/*.min.js``) is treated as a plain
        file glob via ``fnmatch``, unchanged.

        ``is_dir`` says whether ``rel_path`` names a directory. The walk branch prunes
        directories and so passes it; the file branch does not. It matters because a
        directory pattern must not match a *file* whose own name fits it: ``venv*/**``
        means "any venv directory", never ``src/venv_helper.py``.
        """
        return any(
            self._matches_exclude_pattern(rel_path, pattern, is_dir=is_dir)
            for pattern in self.exclude
        )

    def _matches_exclude_pattern(
        self, rel_path: str, pattern: str, *, is_dir: bool = False
    ) -> bool:
        normalized = pattern.rstrip("/")
        if not normalized.endswith("/**"):
            return self._matches_any(rel_path, [pattern])
        base = normalized[:-3]
        # ``**/dir/**`` and the bare ``dir/**`` mean the same thing: exclude that
        # directory wherever it sits. Only a multi-segment base without the ``**/``
        # prefix (e.g. ``.pi/npm/**``) is anchored at the repository root.
        any_depth = base.startswith("**/")
        if any_depth:
            base = base[3:]
        if not base:
            return True
        if any_depth or "/" not in base:
            segments = rel_path.split("/")
            # For a file path the run has to end above the file itself -- the pattern
            # excludes a directory's contents, so the last segment is never the match.
            # For a directory path (walk pruning) the run may end at the directory.
            searchable = segments if is_dir else segments[:-1]
            return self._contains_segment_run(searchable, base.split("/"))
        return rel_path == base or rel_path.startswith(base + "/")

    @staticmethod
    def _contains_segment_run(path_segments: list[str], run: list[str]) -> bool:
        """True when ``run`` appears as a contiguous run of path segments.

        Matching a run rather than a substring keeps ``node_modules/**`` from
        excluding ``src/node_modules_helper.py``. Segments are compared with
        ``fnmatch`` so a wildcard inside the base (``**/*_generated/**``) still works.
        """
        span = len(run)
        return any(
            all(
                fnmatch.fnmatch(segment, expected)
                for segment, expected in zip(path_segments[offset : offset + span], run, strict=True)
            )
            for offset in range(len(path_segments) - span + 1)
        )

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
            digest = hashlib.sha1(f"{rel_path}:{start_line}:{end_line}".encode()).hexdigest()[:12]
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

    def _documentation_chunks(self, rel_path: str, text: str) -> list[CodeItem]:
        chunks: list[CodeItem] = []
        for chunk in self._line_chunks(rel_path, text):
            chunks.append(
                CodeItem(
                    id=chunk.id.replace("#", "::doc_chunk#"),
                    path=chunk.path,
                    title=f"{chunk.title}::doc_chunk",
                    content=chunk.content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    metadata={
                        CodeItemMetadata.SOURCE: "scanner",
                        CodeItemMetadata.INDEX_KIND: CodeItemIndexKind.DOC_CHUNK,
                        CodeItemMetadata.KIND: "documentation",
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
            digest = hashlib.sha1(f"{rel_path}:{symbol.name}:{start_line}:{end_line}".encode()).hexdigest()[:12]
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
