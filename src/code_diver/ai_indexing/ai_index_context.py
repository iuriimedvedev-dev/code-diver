from __future__ import annotations

from dataclasses import dataclass

from .ai_index_candidate import AiIndexCandidate


@dataclass(slots=True)
class AiIndexContext:
    tree: str
    discoveries: list[str]
    candidates: list[AiIndexCandidate]
