from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import AppConfig
from ..experiments import ExperimentRun
from .case_metric_row import CaseMetricRow
from .metric_row import MetricRow


class ExperimentMetricsMapper:
    def to_rows(
        self,
        run: ExperimentRun,
        config: AppConfig,
        config_path: Path | None,
    ) -> tuple[list[MetricRow], list[CaseMetricRow]]:
        event_time = self._event_time()
        repository = str(config.root.resolve())
        dataset = str(config.evaluation.dataset)
        metadata = {
            "config_path": str(config_path) if config_path else None,
            "artifact": str(config.artifact),
            "embedding_provider": config.embedding.provider,
            "embedding_model": config.embedding.model,
            "indexing_mode": config.indexing.mode,
            "scanner_structural_chunks": config.scanner.structural_chunks,
            "scanner_symbol_chunks": config.scanner.symbol_chunks,
            "storage_provider": config.storage.provider,
            "hybrid_file_vote_weight": config.hybrid_search.file_vote_weight,
            "hybrid_vector_kind_limits": config.hybrid_search.vector_kind_limits,
            "hybrid_vector_kind_multipliers": config.hybrid_search.vector_kind_multipliers,
        }
        metric_rows: list[MetricRow] = []
        case_rows: list[CaseMetricRow] = []
        for strategy_result in run.strategy_results:
            strategy_metadata = {
                **metadata,
                "duration_ms": strategy_result.duration_ms,
            }
            for name, value in strategy_result.metrics.items():
                if isinstance(value, int | float):
                    metric_rows.append(
                        MetricRow(
                            event_time=event_time,
                            run_id=run.run_id,
                            suite=run.suite,
                            repository=repository,
                            dataset=dataset,
                            strategy=strategy_result.strategy,
                            metric_name=name,
                            metric_value=float(value),
                            metadata_json=json.dumps(strategy_metadata, sort_keys=True),
                        )
                    )
            for result in strategy_result.results:
                case_rows.append(
                    CaseMetricRow(
                        event_time=event_time,
                        run_id=run.run_id,
                        suite=run.suite,
                        repository=repository,
                        dataset=dataset,
                        strategy=strategy_result.strategy,
                        case_id=result.case_id,
                        query=result.query,
                        hit=1 if result.hit else 0,
                        reciprocal_rank=float(result.reciprocal_rank),
                        precision=float(result.precision),
                        recall=float(result.recall),
                        expected=result.expected,
                        retrieved=result.retrieved,
                    )
                )
        return metric_rows, case_rows

    def _event_time(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
