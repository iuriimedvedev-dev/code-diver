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
    symbol_match_weight: float = Defaults.HYBRID_SYMBOL_MATCH_WEIGHT
    graph_weight: float = Defaults.HYBRID_GRAPH_WEIGHT
    file_vote_weight: float = Defaults.HYBRID_FILE_VOTE_WEIGHT
    vector_kind_limits: dict[str, int] = field(default_factory=lambda: dict(Defaults.HYBRID_VECTOR_KIND_LIMITS))
    vector_kind_multipliers: dict[str, float] = field(
        default_factory=lambda: dict(Defaults.HYBRID_VECTOR_KIND_MULTIPLIERS)
    )
    graph_depth: int = Defaults.HYBRID_GRAPH_DEPTH
    graph_neighbor_limit: int = Defaults.HYBRID_GRAPH_NEIGHBOR_LIMIT
    lexical_scoring: str = Defaults.HYBRID_LEXICAL_SCORING
    fusion: str = Defaults.HYBRID_FUSION
    rrf_k: int = Defaults.HYBRID_RRF_K
    bm25_k1: float = Defaults.HYBRID_BM25_K1
    bm25_b: float = Defaults.HYBRID_BM25_B
    routing_enabled: bool = Defaults.HYBRID_ROUTING_ENABLED
    preserve_vector_top: bool = Defaults.HYBRID_PRESERVE_VECTOR_TOP
    vector_top_score_margin: float = Defaults.HYBRID_VECTOR_TOP_SCORE_MARGIN
    item_kind_weights: dict[str, float] = field(default_factory=lambda: dict(Defaults.HYBRID_ITEM_KIND_WEIGHTS))
    min_token_length: int = Defaults.HYBRID_MIN_TOKEN_LENGTH
    stop_words: list[str] = field(default_factory=lambda: list(Defaults.HYBRID_STOP_WORDS))
