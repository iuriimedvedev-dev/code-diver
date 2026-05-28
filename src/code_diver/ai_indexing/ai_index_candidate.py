from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AiIndexCandidate:
    path: str
    content: str
    start_line: int | None
    end_line: int | None
