from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class ExperimentsConfig:
    suite: str = Defaults.EXPERIMENT_SUITE
    strategies: list[str] = field(default_factory=lambda: list(Defaults.EXPERIMENT_STRATEGIES))
