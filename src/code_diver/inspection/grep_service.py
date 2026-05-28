from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


@dataclass(slots=True)
class GrepMatch:
    path: str
    line: int
    text: str


class GrepService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root)

    def search(self, pattern: str, path: str | None = None, limit: int = 100, regex: bool = False) -> list[GrepMatch]:
        compiled = re.compile(pattern) if regex else None
        matches: list[GrepMatch] = []
        for file_path in self._files(self.guard.resolve(path)):
            for line_number, line in enumerate(self._lines(file_path), start=1):
                if self._matches(line, pattern, compiled):
                    matches.append(
                        GrepMatch(
                            path=file_path.relative_to(self.root).as_posix(),
                            line=line_number,
                            text=line.rstrip("\n"),
                        )
                    )
                    if len(matches) >= limit:
                        return matches
        return matches

    def render(self, pattern: str, path: str | None = None, limit: int = 100, regex: bool = False) -> str:
        return "\n".join(
            f"{match.path}:{match.line}: {match.text}" for match in self.search(pattern, path, limit, regex)
        )

    def _files(self, start: Path):
        if start.is_file():
            if not self.ignore.ignored(start):
                yield start
            return
        for path in sorted(start.rglob("*")):
            if path.is_file() and not self.ignore.ignored(path) and not self._binary(path):
                yield path

    def _lines(self, path: Path):
        try:
            yield from path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return

    def _matches(self, line: str, pattern: str, compiled: re.Pattern[str] | None) -> bool:
        if compiled is not None:
            return bool(compiled.search(line))
        return pattern in line

    def _binary(self, path: Path) -> bool:
        try:
            return b"\x00" in path.read_bytes()[:2048]
        except OSError:
            return True
