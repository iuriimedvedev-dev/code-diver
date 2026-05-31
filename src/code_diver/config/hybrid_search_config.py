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
    lexical_scoring: str = Defaults.HYBRID_LEXICAL_SCORING
    fusion: str = Defaults.HYBRID_FUSION
    rrf_k: int = Defaults.HYBRID_RRF_K
    bm25_k1: float = Defaults.HYBRID_BM25_K1
    bm25_b: float = Defaults.HYBRID_BM25_B
    min_token_length: int = Defaults.HYBRID_MIN_TOKEN_LENGTH
    stop_words: list[str] = field(default_factory=lambda: list(Defaults.HYBRID_STOP_WORDS))
