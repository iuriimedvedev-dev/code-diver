from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..domain import CodeItem


class CodeItemScanner(Protocol):
    def scan(self, root: Path) -> list[CodeItem]:
        pass
