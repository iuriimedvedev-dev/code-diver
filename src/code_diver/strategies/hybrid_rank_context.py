from __future__ import annotations

from dataclasses import dataclass

from ..config import HybridSearchConfig
from ..domain import SearchResult
from .hybrid_candidate_score import HybridCandidateScore


@dataclass(slots=True)
class HybridRankContext:
    query: str
    route_name: str
    scores: dict[str, HybridCandidateScore]
    vector_results: list[SearchResult]
    config: HybridSearchConfig
    effective_graph_depth: int
    effective_graph_neighbor_limit: int
    graph_candidate_count: int
