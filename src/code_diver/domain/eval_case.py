from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EvalCase:
    id: str
    query: str
    expected: list[str]
