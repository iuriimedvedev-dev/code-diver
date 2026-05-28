from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class MetricsConfig:
    enabled: bool = Defaults.METRICS_ENABLED
    url: str = Defaults.CLICKHOUSE_URL
    database: str = Defaults.CLICKHOUSE_DATABASE
    username: str = Defaults.CLICKHOUSE_USERNAME
    password: str = Defaults.CLICKHOUSE_PASSWORD
    docker_container: str | None = None
    metrics_table: str = Defaults.CLICKHOUSE_METRICS_TABLE
    cases_table: str = Defaults.CLICKHOUSE_CASES_TABLE
    timeout_seconds: float = Defaults.CLICKHOUSE_TIMEOUT_SECONDS
    retention_days: int = Defaults.CLICKHOUSE_RETENTION_DAYS
