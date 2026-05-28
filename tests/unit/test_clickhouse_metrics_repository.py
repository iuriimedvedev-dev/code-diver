from __future__ import annotations

import pytest

from code_diver.metrics import CaseMetricRow, ClickHouseMetricsRepository, MetricRow


pytestmark = pytest.mark.unit


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.inserts: list[tuple[str, list[object]]] = []

    def execute(self, query: str) -> str:
        self.queries.append(query)
        return ""

    def insert_json_each_row(self, table: str, rows: list[object]) -> None:
        self.inserts.append((table, rows))


def test_clickhouse_repository_creates_schema_and_saves_rows() -> None:
    client = FakeClickHouseClient()
    repository = ClickHouseMetricsRepository(
        client,
        database="code_diver",
        metrics_table="rag_eval_metrics",
        cases_table="rag_eval_cases",
        retention_days=14,
    )

    repository.ensure_schema()
    repository.save(
        [
            MetricRow(
                event_time="2026-05-28 10:00:00.000",
                run_id="run",
                suite="suite",
                repository="/repo",
                dataset="dataset.jsonl",
                strategy="vector",
                metric_name="hit_rate@10",
                metric_value=1.0,
                metadata_json="{}",
            )
        ],
        [
            CaseMetricRow(
                event_time="2026-05-28 10:00:00.000",
                run_id="run",
                suite="suite",
                repository="/repo",
                dataset="dataset.jsonl",
                strategy="vector",
                case_id="case",
                query="query",
                hit=1,
                reciprocal_rank=1.0,
                precision=0.1,
                recall=1.0,
                expected=["src/main.py"],
                retrieved=["src/main.py#abc"],
            )
        ],
    )

    ddl = "\n".join(client.queries)
    assert "CREATE DATABASE IF NOT EXISTS `code_diver`" in ddl
    assert "TTL event_time + INTERVAL 14 DAY DELETE" in ddl
    assert client.inserts[0][0] == "`code_diver`.`rag_eval_metrics`"
    assert client.inserts[1][0] == "`code_diver`.`rag_eval_cases`"
