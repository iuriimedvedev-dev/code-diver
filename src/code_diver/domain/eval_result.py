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
    retrieved_files: list[str] | None = None
    file_hit: bool = False
    file_reciprocal_rank: float = 0.0
    file_precision_at_r: float = 0.0
    file_recall: float = 0.0
    ndcg: float = 0.0
    average_precision: float = 0.0
