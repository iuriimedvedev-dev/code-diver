from __future__ import annotations

from pathlib import Path


class PathGuard:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, path: str | None = None) -> Path:
        candidate = (self.root / (path or ".")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError(f"Path escapes repository root: {path}")
        return candidate
