from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AnswerContext:
    text: str
    files: list[str] = field(default_factory=list)
    file_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
