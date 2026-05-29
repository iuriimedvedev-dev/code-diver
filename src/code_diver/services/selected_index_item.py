from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SelectedIndexItem:
    path: str
    start_line: int | None = None
    end_line: int | None = None
    title: str | None = None
    reason: str | None = None
    kind: str | None = None
