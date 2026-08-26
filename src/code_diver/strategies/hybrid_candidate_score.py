from __future__ import annotations

from dataclasses import dataclass

from ..config import HybridSearchConfig
from ..domain import CodeItem
from ..native_search import fuse_hybrid_total


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
        python_total = (
            self.vector_score * config.vector_weight
            + self.lexical_score * config.lexical_weight
            + self.path_score * config.path_weight
            + self.symbol_score * config.symbol_weight
            + self.symbol_match_score * config.symbol_match_weight
            + self.graph_score * config.graph_weight
            + self.file_vote_score * config.file_vote_weight
        )
        return fuse_hybrid_total(
            vector=self.vector_score,
            lexical=self.lexical_score,
            path=self.path_score,
            symbol=self.symbol_score,
            symbol_match=self.symbol_match_score,
            graph=self.graph_score,
            file_vote=self.file_vote_score,
            vector_weight=config.vector_weight,
            lexical_weight=config.lexical_weight,
            path_weight=config.path_weight,
            symbol_weight=config.symbol_weight,
            symbol_match_weight=config.symbol_match_weight,
            graph_weight=config.graph_weight,
            file_vote_weight=config.file_vote_weight,
            python_fallback=python_total,
        )
