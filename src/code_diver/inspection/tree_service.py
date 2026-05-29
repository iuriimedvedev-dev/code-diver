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
        structured = self.list_entries(path=path, max_depth=max_depth, limit=limit)
        lines: list[str] = [structured["root"]]
        for entry in structured["entries"]:
            prefix = "  " * int(entry["depth"])
            suffix = "/" if entry["kind"] == "directory" else ""
            lines.append(f"{prefix}{entry['name']}{suffix}")
        if structured["metrics"]["truncated"]:
            lines.append("...")
        return "\n".join(lines)

    def list_entries(self, path: str | None = None, max_depth: int = 3, limit: int = 200) -> dict:
        start = self.guard.resolve(path)
        entries: list[dict] = []
        count = 0
        for current, depth in self._walk(start, max_depth):
            if count >= limit:
                break
            rel_path = current.relative_to(self.root).as_posix()
            entries.append(
                {
                    "path": rel_path,
                    "name": current.name,
                    "kind": "directory" if current.is_dir() else "file",
                    "depth": depth,
                }
            )
            count += 1
        return {
            "root": self._label(start),
            "entries": entries,
            "metrics": {
                "entryCount": len(entries),
                "limit": limit,
                "maxDepth": max_depth,
                "truncated": count >= limit,
            },
        }

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
