from __future__ import annotations

import os
from pathlib import Path


class EnvFileLoader:
    def load(self, path: Path, override: bool = False) -> None:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            key, value = self._parse_line(line)
            if not key:
                continue
            if not override and key in os.environ:
                continue
            os.environ[key] = value

    def _parse_line(self, line: str) -> tuple[str | None, str]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            return None, ""
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return key, value
