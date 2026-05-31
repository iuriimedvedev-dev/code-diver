from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class HybridSearchConfig:
    candidate_limit: int = Defaults.HYBRID_CANDIDATE_LIMIT
    lexical_candidate_limit: int = Defaults.HYBRID_LEXICAL_CANDIDATE_LIMIT
    vector_weight: float = Defaults.HYBRID_VECTOR_WEIGHT
    lexical_weight: float = Defaults.HYBRID_LEXICAL_WEIGHT
    path_weight: float = Defaults.HYBRID_PATH_WEIGHT
    symbol_weight: float = Defaults.HYBRID_SYMBOL_WEIGHT
    graph_weight: float = Defaults.HYBRID_GRAPH_WEIGHT
    graph_depth: int = Defaults.HYBRID_GRAPH_DEPTH
    graph_neighbor_limit: int = Defaults.HYBRID_GRAPH_NEIGHBOR_LIMIT
    min_token_length: int = Defaults.HYBRID_MIN_TOKEN_LENGTH
    stop_words: list[str] = field(default_factory=lambda: list(Defaults.HYBRID_STOP_WORDS))
