from __future__ import annotations

from dataclasses import dataclass, field

from .hybrid_search_config import HybridSearchConfig


@dataclass(slots=True)
class ExperimentHypothesisConfig:
    name: str
    strategy: str | None = None
    toolset: str | None = None
    tools: list[str] = field(default_factory=list)
    hybrid_search: HybridSearchConfig | None = None
    description: str | None = None
