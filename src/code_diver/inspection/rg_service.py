from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .grep_service import GrepService
from .path_guard import PathGuard


class RgService:
    def __init__(
        self,
        root: Path,
        exclude: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
        timeout_seconds: float = 10.0,
    ):
        self.root = root.resolve()
        self.guard = PathGuard(self.root)
        self.exclude = exclude or []
        self.max_file_bytes = max_file_bytes
        self.timeout_seconds = timeout_seconds

    def search(self, pattern: str, path: str | None = None, limit: int = 100) -> str:
        if shutil.which("rg") is None:
            return GrepService(self.root, self.exclude, self.max_file_bytes).render(pattern, path, limit, regex=True)
        target = self.guard.resolve(path)
        command = [
            "rg",
            "--with-filename",
            "--line-number",
            "--color",
            "never",
            "--max-count",
            str(limit),
            "--max-filesize",
            str(self.max_file_bytes),
            *self._exclude_args(),
            pattern,
            str(target.relative_to(self.root) if target != self.root else "."),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"rg timed out after {self.timeout_seconds}s") from exc
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "rg failed")
        lines = completed.stdout.splitlines()[:limit]
        return "\n".join(lines)

    def _exclude_args(self) -> list[str]:
        args: list[str] = []
        for pattern in self.exclude:
            args.extend(["--glob", f"!{pattern}"])
        return args
