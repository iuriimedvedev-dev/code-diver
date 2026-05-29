from __future__ import annotations

from pathlib import Path

from .ignore_matcher import IgnoreMatcher
from .path_guard import PathGuard


class TreeService:
    def __init__(self, root: Path, exclude: list[str] | None = None):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.ignore = IgnoreMatcher(self.root, exclude)

    def render(self, path: str | None = None, max_depth: int = 3, limit: int = 200) -> str:
        start = self.guard.resolve(path)
        lines: list[str] = [self._label(start)]
        count = 0
        for current, depth in self._walk(start, max_depth):
            if count >= limit:
                lines.append("...")
                break
            rel = current.relative_to(start)
            prefix = "  " * depth
            suffix = "/" if current.is_dir() else ""
            lines.append(f"{prefix}{rel.name}{suffix}")
            count += 1
        return "\n".join(lines)

    def _walk(self, start: Path, max_depth: int):
        if not start.is_dir():
            return
        stack = [(child, 1) for child in reversed(self._children(start))]
        while stack:
            current, depth = stack.pop()
            yield current, depth
            if current.is_dir() and depth < max_depth:
                stack.extend((child, depth + 1) for child in reversed(self._children(current)))

    def _children(self, path: Path) -> list[Path]:
        try:
            children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError:
            return []
        return [child for child in children if not self.ignore.ignored(child)]

    def _label(self, path: Path) -> str:
        if path == self.root:
            return "."
        return path.relative_to(self.root).as_posix()
