from __future__ import annotations

from pathlib import Path

from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


class ReadExcerptService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root)

    def render(self, path: str, start_line: int = 1, lines: int = 80) -> str:
        target = self.guard.resolve(path)
        if self.ignore.ignored(target):
            raise ValueError(f"Path is ignored: {path}")
        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")
        bounded_start = max(start_line, 1)
        bounded_lines = min(max(lines, 1), 400)
        text_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        end_line = min(bounded_start + bounded_lines - 1, len(text_lines))
        selected = text_lines[bounded_start - 1 : end_line]
        rel_path = target.relative_to(self.root).as_posix()
        body = "\n".join(f"{line_number:>5} | {line}" for line_number, line in enumerate(selected, start=bounded_start))
        return f"{rel_path}:{bounded_start}-{end_line}\n{body}"
