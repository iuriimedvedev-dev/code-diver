from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain import EvalCase


class DatasetLoader:
    def load(self, path: Path) -> list[EvalCase]:
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")
        if path.suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload["cases"] if isinstance(payload, dict) else payload
        return [self._case_from_row(row, index) for index, row in enumerate(rows)]

    def _case_from_row(self, row: dict[str, Any], index: int) -> EvalCase:
        expected = row.get("expected") or row.get("relevant") or row.get("answers")
        if isinstance(expected, str):
            expected = [expected]
        if not expected:
            raise ValueError(f"Dataset row {index} must include expected/relevant ids or paths.")
        return EvalCase(
            id=str(row.get("id") or f"case-{index + 1}"),
            query=str(row["query"]),
            expected=[str(value) for value in expected],
        )
