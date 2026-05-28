from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EvalResult:
    case_id: str
    query: str
    expected: list[str]
    retrieved: list[str]
    hit: bool
    reciprocal_rank: float
    precision: float
    recall: float
