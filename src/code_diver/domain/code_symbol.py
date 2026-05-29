from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CodeSymbol:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
