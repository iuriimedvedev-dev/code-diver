from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class VertexBatchTestOptions:
    submit: bool = False
    model: str | None = None
    gcs_uri: str | None = None
    local_dir: Path | None = None
    prompt: str = 'Return JSON only: {"ok": true, "vertex_batch_test": true}'
    max_output_tokens: int = 64
