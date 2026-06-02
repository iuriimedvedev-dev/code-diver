from __future__ import annotations

from dataclasses import dataclass

from ..domain import SearchResult


@dataclass(frozen=True, slots=True)
class EphemeralDeepSearchResult:
    results: list[SearchResult]
    query_ms: float
