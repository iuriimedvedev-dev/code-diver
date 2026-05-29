from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import CodeItem


@dataclass(slots=True)
class SelectedIndexResult:
    items: list[CodeItem]
    skipped: list[str] = field(default_factory=list)
