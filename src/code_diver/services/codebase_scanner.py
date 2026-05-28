from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path

from ..domain import CodeItem

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
    ):
        self.include = include or []
        self.exclude = [*DEFAULT_EXCLUDES, *(exclude or [])]
        self.max_file_bytes = max_file_bytes
        self.chunk_lines = chunk_lines

    def scan(self, root: Path) -> list[CodeItem]:
        root = root.resolve()
        items: list[CodeItem] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(root).as_posix()
            if self._matches_any(rel_path, self.exclude):
                continue
            if self.include and not self._matches_any(rel_path, self.include):
                continue
            if not self.include and path.suffix.lower() not in DEFAULT_INCLUDE_SUFFIXES:
                continue
            text = self._read_text(path)
            if text is None or not text.strip():
                continue
            items.extend(self._chunk_file(rel_path, text))
        return items

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
                    metadata={"source": "scanner"},
                )
            )
        return chunks

    def _matches_any(self, rel_path: str, patterns: list[str]) -> bool:
        return any(
            fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(f"./{rel_path}", pattern)
            for pattern in patterns
        )
