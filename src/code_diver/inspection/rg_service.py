from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .grep_service import GrepService
from .path_guard import PathGuard


class RgService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)

    def search(self, pattern: str, path: str | None = None, limit: int = 100) -> str:
        if shutil.which("rg") is None:
            return GrepService(self.root).render(pattern, path, limit, regex=True)
        target = self.guard.resolve(path)
        command = [
            "rg",
            "--line-number",
            "--color",
            "never",
            "--max-count",
            str(limit),
            pattern,
            str(target.relative_to(self.root) if target != self.root else "."),
        ]
        completed = subprocess.run(command, cwd=self.root, text=True, capture_output=True, check=False)
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "rg failed")
        lines = completed.stdout.splitlines()[:limit]
        return "\n".join(lines)
