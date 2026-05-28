from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class RecursiveSearchConfig:
    rounds: int = Defaults.RECURSIVE_ROUNDS
    branch_limit: int = Defaults.RECURSIVE_BRANCH_LIMIT
    limit: int = Defaults.RECURSIVE_PER_ROUND_LIMIT
