from __future__ import annotations

from pathlib import Path

from ..domain import CodeItem
from ..inspection.path_guard import PathGuard
from .codebase_scanner import CodebaseScanner


class CandidateFileScanner:
    def __init__(self, scanner: CodebaseScanner):
        self.scanner = scanner

    def scan_files(self, root: Path, files: list[str]) -> list[CodeItem]:
        resolved_root = root.resolve()
        guard = PathGuard(resolved_root)
        items: list[CodeItem] = []
        seen: set[str] = set()
        for file in files:
            path = guard.resolve(file)
            rel_path = path.relative_to(resolved_root).as_posix()
            if rel_path in seen:
                continue
            seen.add(rel_path)
            if not path.is_file() or self.scanner._should_skip_file(path, rel_path):
                continue
            text = self.scanner._read_text(path)
            if text is None or not text.strip():
                continue
            items.extend(self.scanner._items_for_file(rel_path, text))
        return items
