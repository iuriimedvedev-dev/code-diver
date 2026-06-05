from __future__ import annotations

import json
from pathlib import Path

from .answer_case import AnswerCase


class AnswerDatasetLoader:
    def load(self, path: Path) -> list[AnswerCase]:
        cases: list[AnswerCase] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    cases.append(AnswerCase.from_json(json.loads(stripped)))
                except Exception as exc:
                    raise ValueError(f"Invalid answer dataset row {line_number} in {path}: {exc}") from exc
        return cases
