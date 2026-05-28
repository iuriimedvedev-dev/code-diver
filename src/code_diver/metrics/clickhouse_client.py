from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ClickHouseClient:
    def __init__(self, url: str, username: str, password: str, timeout_seconds: float):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds

    def execute(self, query: str) -> str:
        return self._post(query.encode("utf-8"))

    def insert_json_each_row(self, table: str, rows: list[Any]) -> None:
        if not rows:
            return
        payload = "\n".join(json.dumps(asdict(row), ensure_ascii=False) for row in rows)
        query = f"INSERT INTO {table} FORMAT JSONEachRow\n{payload}"
        self._post(query.encode("utf-8"))

    def _post(self, body: bytes) -> str:
        request = Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "X-ClickHouse-User": self.username,
                "X-ClickHouse-Key": self.password,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ClickHouse request failed: HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"ClickHouse is not reachable at {self.url}: {exc.reason}") from exc


def quote_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"Unsafe ClickHouse identifier: {value}")
    return f"`{value}`"
