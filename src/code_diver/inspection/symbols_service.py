from __future__ import annotations

from pathlib import Path

from ..services import CodeSymbolExtractor
from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


class SymbolsService:
    def __init__(self, root: Path, exclude: list[str] | None = None, max_file_bytes: int = 1_000_000):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root, exclude)
        self.extractor = CodeSymbolExtractor()
        self.max_file_bytes = max_file_bytes

    def render(self, path: str | None = None, limit: int = 200) -> str:
        rows: list[str] = []
        for file_path in self._files(self.guard.resolve(path)):
            rel_path = file_path.relative_to(self.root).as_posix()
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for symbol in self.extractor.extract(rel_path, text):
                rows.append(f"{rel_path}:{symbol.start_line}: {symbol.kind} {symbol.name} - {symbol.signature}")
                if len(rows) >= limit:
                    return "\n".join(rows)
        return "\n".join(rows)

    def _files(self, start: Path):
        if start.is_file():
            if not self.ignore.ignored(start):
                yield start
            return
        for path in sorted(start.rglob("*")):
            if (
                path.is_file()
                and not self.ignore.ignored(path)
                and path.suffix.lower() in self._suffixes()
                and self._within_size_limit(path)
            ):
                yield path

    def _suffixes(self) -> set[str]:
        return {".go", ".java", ".js", ".jsx", ".kt", ".py", ".rs", ".ts", ".tsx"}

    def _within_size_limit(self, path: Path) -> bool:
        try:
            return path.stat().st_size <= self.max_file_bytes
        except OSError:
            return False
