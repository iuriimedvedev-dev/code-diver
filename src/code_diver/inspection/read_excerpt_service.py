from __future__ import annotations

from pathlib import Path
from typing import Any

from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


class ReadExcerptService:
    def __init__(self, root: Path, exclude: list[str] | None = None, max_file_bytes: int = 1_000_000):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root, exclude)
        self.max_file_bytes = max_file_bytes

    def render(self, path: str, start_line: int = 1, lines: int = 80) -> str:
        structured = self.structured(path, start_line=start_line, lines=lines)
        body = "\n".join(
            f"{line['line']:>5} | {line['text']}" for line in structured["lines"]
        )
        return f"{structured['path']}:{structured['startLine']}-{structured['endLine']}\n{body}"

    def structured(self, path: str, start_line: int = 1, lines: int = 80) -> dict[str, Any]:
        target = self.guard.resolve(path)
        if self.ignore.ignored(target):
            raise ValueError(f"Path is ignored: {path}")
        if not target.is_file():
            raise ValueError(f"Path is not a file: {path}")
        if target.stat().st_size > self.max_file_bytes:
            raise ValueError(f"Path exceeds max file size: {path}")
        bounded_start = max(start_line, 1)
        bounded_lines = min(max(lines, 1), 400)
        text_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        end_line = min(bounded_start + bounded_lines - 1, len(text_lines))
        selected = text_lines[bounded_start - 1 : end_line]
        rel_path = target.relative_to(self.root).as_posix()
        return {
            "path": rel_path,
            "startLine": bounded_start,
            "endLine": end_line,
            "lineCount": len(selected),
            "lines": [
                {"line": line_number, "text": line}
                for line_number, line in enumerate(selected, start=bounded_start)
            ],
            "metrics": {
                "requestedLines": lines,
                "returnedLines": len(selected),
                "fileLines": len(text_lines),
                "truncated": bounded_lines < lines or end_line < min(start_line + lines - 1, len(text_lines)),
            },
        }
