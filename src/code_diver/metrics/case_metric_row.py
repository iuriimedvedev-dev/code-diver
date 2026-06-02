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
    retrieved_files: list[str]
    file_hit: int
    file_reciprocal_rank: float
    file_precision_at_r: float
    file_recall: float
    ndcg: float
    average_precision: float
    bucket: str
    top_result_kind: str
    first_relevant_kind: str
    expected_count: int
    retrieved_count: int
    retrieved_file_count: int
