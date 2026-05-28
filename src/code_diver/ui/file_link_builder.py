from __future__ import annotations

from pathlib import Path


class FileLinkBuilder:
    def build(self, root: Path, path: str, line: int, enabled: bool) -> str:
        label = f"{path}:{line}"
        if not enabled:
            return label
        absolute_path = (root / path).resolve()
        return f"[link=file://{absolute_path}:{line}]{label}[/link]"
