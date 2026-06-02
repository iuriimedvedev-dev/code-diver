from __future__ import annotations

from enum import StrEnum


class RetrievalStrategyId(StrEnum):
    ORCHESTRATED = "orchestrated"
    VECTOR = "vector"
    RECURSIVE = "recursive"
    GRAPH = "graph"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
    CROSS_ENCODER_RERANK = "cross_encoder_rerank"
