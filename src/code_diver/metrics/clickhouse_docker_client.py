from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from typing import Any


class ClickHouseDockerClient:
    def __init__(self, container: str, username: str, password: str, timeout_seconds: float):
        self.container = container
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds

    def execute(self, query: str) -> str:
        return self._run(["--multiquery", "--query", query])

    def insert_json_each_row(self, table: str, rows: list[Any]) -> None:
        if not rows:
            return
        payload = "\n".join(json.dumps(asdict(row), ensure_ascii=False) for row in rows)
        self._run(["--query", f"INSERT INTO {table} FORMAT JSONEachRow"], stdin=payload)

    def _run(self, args: list[str], stdin: str | None = None) -> str:
        command = [
            "docker",
            "exec",
            "-i",
            self.container,
            "clickhouse-client",
            "--user",
            self.username,
            "--password",
            self.password,
            *args,
        ]
        try:
            completed = subprocess.run(
                command,
                input=stdin,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"ClickHouse docker client failed: {exc.stderr or exc.stdout}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"ClickHouse docker client timed out after {self.timeout_seconds}s") from exc
        return completed.stdout
