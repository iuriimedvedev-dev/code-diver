from __future__ import annotations

from .case_metric_row import CaseMetricRow
from .clickhouse_client import quote_identifier
from .clickhouse_writer import ClickHouseWriter
from .metric_row import MetricRow


class ClickHouseMetricsRepository:
    def __init__(
        self,
        client: ClickHouseWriter,
        database: str,
        metrics_table: str,
        cases_table: str,
        retention_days: int,
    ):
        self.client = client
        self.database = database
        self.metrics_table = metrics_table
        self.cases_table = cases_table
        self.retention_days = retention_days

    def ensure_schema(self) -> None:
        database = quote_identifier(self.database)
        metrics_table = self._table_name(self.metrics_table)
        cases_table = self._table_name(self.cases_table)
        retention_days = max(int(self.retention_days), 1)
        self.client.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
        self.client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {metrics_table}
            (
                event_time DateTime64(3, 'UTC'),
                run_id String,
                suite LowCardinality(String),
                repository String,
                dataset String,
                strategy LowCardinality(String),
                metric_name LowCardinality(String),
                metric_value Float64,
                metadata_json String
            )
            ENGINE = MergeTree
            ORDER BY (suite, strategy, metric_name, event_time)
            TTL event_time + INTERVAL {retention_days} DAY DELETE
            """.strip()
        )
        self.client.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {cases_table}
            (
                event_time DateTime64(3, 'UTC'),
                run_id String,
                suite LowCardinality(String),
                repository String,
                dataset String,
                strategy LowCardinality(String),
                case_id String,
                query String,
                hit UInt8,
                reciprocal_rank Float64,
                precision Float64,
                recall Float64,
                expected Array(String),
                retrieved Array(String)
            )
            ENGINE = MergeTree
            ORDER BY (suite, strategy, case_id, event_time)
            TTL event_time + INTERVAL {retention_days} DAY DELETE
            """.strip()
        )

    def save(self, metrics: list[MetricRow], cases: list[CaseMetricRow]) -> None:
        self.client.insert_json_each_row(self._table_name(self.metrics_table), metrics)
        self.client.insert_json_each_row(self._table_name(self.cases_table), cases)

    def _table_name(self, table: str) -> str:
        return f"{quote_identifier(self.database)}.{quote_identifier(table)}"
