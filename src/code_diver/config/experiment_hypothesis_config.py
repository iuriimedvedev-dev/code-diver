from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExperimentHypothesisConfig:
    name: str
    strategy: str | None = None
    toolset: str | None = None
    tools: list[str] = field(default_factory=list)
    description: str | None = None
