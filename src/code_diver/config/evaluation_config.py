from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class EvaluationConfig:
    dataset: Path = Defaults.DATASET
    limit: int = Defaults.SEARCH_LIMIT
    workers: int = Defaults.EVALUATION_WORKERS
    restrict_citations_to_context: bool = False
    """Name the citable files in the answer prompt and forbid citing anything else.

    `citation_fabricated_rate` counts a cited path that is in no context file the model was
    shown. h28 broke that guardrail (0.025 -> 0.053) without retrieving any worse -- on the
    cases that regressed, `candidate_file_recall` moved by exactly 0.000 while citations rose
    from 4.20 to 5.13 per case, and the fabricated paths were real repo files the model had
    simply not been given. A reordered bundle changed the prompt and the model reached beyond
    it. Off by default: every run before h28 was measured without this, and turning it on
    silently would make the whole series incomparable.
    """
