from __future__ import annotations

from typing import Any, Protocol


class ClickHouseWriter(Protocol):
    def execute(self, query: str) -> str:
        pass

    def insert_json_each_row(self, table: str, rows: list[Any]) -> None:
        pass
