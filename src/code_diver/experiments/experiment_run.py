from __future__ import annotations

from dataclasses import dataclass

from .strategy_experiment_result import StrategyExperimentResult


@dataclass(slots=True)
class ExperimentRun:
    run_id: str
    suite: str
    strategy_results: list[StrategyExperimentResult]
