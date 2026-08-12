from __future__ import annotations

from enum import StrEnum


class RetrievalStrategyId(StrEnum):
    ORCHESTRATED = "orchestrated"
    VECTOR = "vector"
    RECURSIVE = "recursive"
    GRAPH = "graph"
    GRAPH_FILE = "graph_file"
    GRAPH_FILE_RERANK = "graph_file_rerank"
    GRAPH_FILE_CROSS_ENCODER = "graph_file_cross_encoder"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
    CROSS_ENCODER_RERANK = "cross_encoder_rerank"
