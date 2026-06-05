from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AnswerContext:
    text: str
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
