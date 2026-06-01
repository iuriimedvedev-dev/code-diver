from __future__ import annotations

from dataclasses import dataclass

from ..config import HybridSearchConfig
from ..domain import CodeItem


@dataclass(slots=True)
class HybridCandidateScore:
    item: CodeItem
    vector_score: float = 0.0
    lexical_score: float = 0.0
    path_score: float = 0.0
    symbol_score: float = 0.0
    symbol_match_score: float = 0.0
    graph_score: float = 0.0
    file_vote_score: float = 0.0

    def total(self, config: HybridSearchConfig) -> float:
        return (
            self.vector_score * config.vector_weight
            + self.lexical_score * config.lexical_weight
            + self.path_score * config.path_weight
            + self.symbol_score * config.symbol_weight
            + self.symbol_match_score * config.symbol_match_weight
            + self.graph_score * config.graph_weight
            + self.file_vote_score * config.file_vote_weight
        )
