from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from ..config import AppConfig
from ..config.experiment_hypothesis_config import ExperimentHypothesisConfig
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
        for hypothesis in self._hypotheses(config):
            if not hypothesis.strategy:
                continue
            strategy_config = replace(config, search=replace(config.search, strategy=hypothesis.strategy))
            if hypothesis.generation is not None:
                strategy_config = replace(strategy_config, generation=hypothesis.generation)
            if hypothesis.hybrid_search is not None:
                strategy_config = replace(strategy_config, hybrid_search=hypothesis.hybrid_search)
            if hypothesis.llm_rerank is not None:
                strategy_config = replace(strategy_config, llm_rerank=hypothesis.llm_rerank)
            if hypothesis.cross_encoder_rerank is not None:
                strategy_config = replace(strategy_config, cross_encoder_rerank=hypothesis.cross_encoder_rerank)
            retrieval_strategy = self.strategy_factory.create(
                hypothesis.strategy,
                strategy_config,
                self.provider,
                self.vector_store,
            )
            started = perf_counter()
            metrics, results = EvaluationService(retrieval_strategy).evaluate(
                cases,
                config.evaluation.limit,
                workers=config.evaluation.workers,
            )
            duration_ms = (perf_counter() - started) * 1000
            metrics["duration_ms"] = duration_ms
            metrics.update(self._index_metrics(config))
            if hypothesis.tools:
                metrics["tools_count"] = len(hypothesis.tools)
            strategy_results.append(
                StrategyExperimentResult(
                    strategy=hypothesis.name,
                    metrics=metrics,
                    results=results,
                    duration_ms=duration_ms,
                )
            )
        return ExperimentRun(run_id=run_id, suite=config.experiments.suite, strategy_results=strategy_results)

    def _hypotheses(self, config: AppConfig) -> list[ExperimentHypothesisConfig]:
        if config.experiments.hypotheses:
            return config.experiments.hypotheses
        return [
            ExperimentHypothesisConfig(name=strategy, strategy=strategy)
            for strategy in config.experiments.strategies
        ]

    def _index_metrics(self, config: AppConfig) -> dict[str, Any]:
        metadata = self._store_metadata()
        item_count = self._item_count()
        dimensions = self._metadata_int(metadata, "dimensions")
        vector_bytes = item_count * dimensions * 4 if item_count is not None and dimensions is not None else None
        metrics: dict[str, Any] = {}
        if item_count is not None:
            metrics["index_items"] = item_count
        if dimensions is not None:
            metrics["index_vector_dimensions"] = dimensions
        if vector_bytes is not None:
            metrics["index_vector_bytes_estimate"] = vector_bytes
            metrics["index_vector_mb_estimate"] = vector_bytes / 1_000_000
        artifact_bytes = self._file_size(config.artifact)
        if artifact_bytes is not None:
            metrics["index_artifact_bytes"] = artifact_bytes
            metrics["index_artifact_mb"] = artifact_bytes / 1_000_000
        graph_bytes = self._file_size(config.graph.artifact)
        if graph_bytes is not None:
            metrics["graph_artifact_bytes"] = graph_bytes
            metrics["graph_artifact_mb"] = graph_bytes / 1_000_000
        return metrics

    def _store_metadata(self) -> dict[str, Any]:
        metadata = getattr(self.vector_store, "metadata", None)
        if not callable(metadata):
            return {}
        try:
            return dict(metadata())
        except Exception:
            return {}

    def _item_count(self) -> int | None:
        count_items = getattr(self.vector_store, "count_items", None)
        if not callable(count_items):
            return None
        try:
            return int(count_items())
        except Exception:
            return None

    def _metadata_int(self, metadata: dict[str, Any], key: str) -> int | None:
        value = metadata.get(key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _file_size(self, path: Path | None) -> int | None:
        if path is None or not path.exists():
            return None
        try:
            return path.stat().st_size
        except OSError:
            return None
