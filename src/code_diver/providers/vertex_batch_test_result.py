from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class VertexBatchTestResult:
    status: str
    model: str
    project: str | None
    location: str
    local_input: Path
    request_count: int
    latency_ms: int = 0
    gcs_input_uri: str | None = None
    gcs_output_uri: str | None = None
    job_name: str | None = None
    job_state: str | None = None
    details: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "dry_run"}

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "model": self.model,
            "project": self.project,
            "location": self.location,
            "local_input": str(self.local_input),
            "request_count": self.request_count,
            "latency_ms": self.latency_ms,
            "gcs_input_uri": self.gcs_input_uri,
            "gcs_output_uri": self.gcs_output_uri,
            "job_name": self.job_name,
            "job_state": self.job_state,
            "details": self.details,
        }
