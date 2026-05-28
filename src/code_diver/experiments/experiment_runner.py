from __future__ import annotations

from dataclasses import replace
from time import perf_counter

from ..config import AppConfig
from ..domain import EvalCase
from ..providers import EmbeddingProvider
from ..services.evaluation_service import EvaluationService
from ..store import VectorStore
from ..strategies import RetrievalStrategyFactory
from .experiment_run import ExperimentRun
from .strategy_experiment_result import StrategyExperimentResult


class ExperimentRunner:
    def __init__(
        self,
        strategy_factory: RetrievalStrategyFactory,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ):
        self.strategy_factory = strategy_factory
        self.provider = provider
        self.vector_store = vector_store

    def run(self, run_id: str, config: AppConfig, cases: list[EvalCase]) -> ExperimentRun:
        strategy_results: list[StrategyExperimentResult] = []
        for strategy in config.experiments.strategies:
            strategy_config = replace(config, search=replace(config.search, strategy=strategy))
            retrieval_strategy = self.strategy_factory.create(
                strategy,
                strategy_config,
                self.provider,
                self.vector_store,
            )
            started = perf_counter()
            metrics, results = EvaluationService(retrieval_strategy).evaluate(cases, config.evaluation.limit)
            duration_ms = (perf_counter() - started) * 1000
            metrics["duration_ms"] = duration_ms
            strategy_results.append(
                StrategyExperimentResult(
                    strategy=strategy,
                    metrics=metrics,
                    results=results,
                    duration_ms=duration_ms,
                )
            )
        return ExperimentRun(run_id=run_id, suite=config.experiments.suite, strategy_results=strategy_results)
