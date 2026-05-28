from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CaseMetricRow:
    event_time: str
    run_id: str
    suite: str
    repository: str
    dataset: str
    strategy: str
    case_id: str
    query: str
    hit: int
    reciprocal_rank: float
    precision: float
    recall: float
    expected: list[str]
    retrieved: list[str]
