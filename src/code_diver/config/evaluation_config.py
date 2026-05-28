from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class EvaluationConfig:
    dataset: Path = Defaults.DATASET
    limit: int = Defaults.SEARCH_LIMIT
