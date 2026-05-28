from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain import EvalResult


@dataclass(slots=True)
class StrategyExperimentResult:
    strategy: str
    metrics: dict[str, Any]
    results: list[EvalResult]
    duration_ms: float
