from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MetricRow:
    event_time: str
    run_id: str
    suite: str
    repository: str
    dataset: str
    strategy: str
    metric_name: str
    metric_value: float
    metadata_json: str
