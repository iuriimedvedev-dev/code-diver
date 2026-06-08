from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class GraphFileSearchConfig:
    seed_limit: int = Defaults.GRAPH_FILE_SEED_LIMIT
    lexical_seed_limit: int = Defaults.GRAPH_FILE_LEXICAL_SEED_LIMIT
    vector_weight: float = Defaults.GRAPH_FILE_VECTOR_WEIGHT
    lexical_weight: float = Defaults.GRAPH_FILE_LEXICAL_WEIGHT
    path_weight: float = Defaults.GRAPH_FILE_PATH_WEIGHT
    symbol_weight: float = Defaults.GRAPH_FILE_SYMBOL_WEIGHT
    graph_weight: float = Defaults.GRAPH_FILE_GRAPH_WEIGHT
    depth: int = Defaults.GRAPH_FILE_DEPTH
    neighbor_limit: int = Defaults.GRAPH_FILE_NEIGHBOR_LIMIT
    decay: float = Defaults.GRAPH_FILE_DECAY
    min_token_length: int = Defaults.GRAPH_FILE_MIN_TOKEN_LENGTH
    stop_words: list[str] = field(default_factory=lambda: list(Defaults.GRAPH_FILE_STOP_WORDS))
