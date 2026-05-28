from __future__ import annotations

from enum import StrEnum


class RetrievalStrategyId(StrEnum):
    VECTOR = "vector"
    RECURSIVE = "recursive"
    GRAPH = "graph"
