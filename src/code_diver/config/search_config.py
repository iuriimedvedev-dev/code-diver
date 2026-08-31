from __future__ import annotations

from dataclasses import dataclass

from ..settings import Defaults


@dataclass(slots=True)
class SearchConfig:
    limit: int = Defaults.SEARCH_LIMIT
    preview_lines: int = Defaults.PREVIEW_LINES
    strategy: str = Defaults.SEARCH_STRATEGY
    persistent_runtime: bool = False
