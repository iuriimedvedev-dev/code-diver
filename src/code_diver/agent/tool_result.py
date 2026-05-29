from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ToolResult:
    name: str
    content: str
    ok: bool = True
