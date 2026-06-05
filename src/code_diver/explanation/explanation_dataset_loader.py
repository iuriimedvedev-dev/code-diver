from __future__ import annotations

import json
from pathlib import Path

from .explanation_case import ExplanationCase


class ExplanationDatasetLoader:
    def load(self, path: Path) -> list[ExplanationCase]:
        cases: list[ExplanationCase] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                cases.append(ExplanationCase.from_json(json.loads(line)))
        return cases
