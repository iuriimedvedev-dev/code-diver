from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class TraceConfig:
    enabled: bool = Defaults.TRACE_ENABLED
    artifact: Path = Defaults.TRACE_ARTIFACT
    include_prompts: bool = Defaults.TRACE_INCLUDE_PROMPTS
