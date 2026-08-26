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
    # How many edges of a single file are followed. Caps fan-out per node.
    neighbor_limit: int = Defaults.GRAPH_FILE_NEIGHBOR_LIMIT
    # How many files survive to the next hop. Caps the breadth of the whole level, which is
    # a different quantity from per-node fan-out: with `neighbor_limit: 40` on a graph whose
    # busiest file has 31 edges, the per-node cap never binds while the level cap decides
    # everything. None keeps the historical behaviour of reusing `neighbor_limit` for both.
    frontier_limit: int | None = None
    decay: float = Defaults.GRAPH_FILE_DECAY
    min_token_length: int = Defaults.GRAPH_FILE_MIN_TOKEN_LENGTH
    stop_words: list[str] = field(default_factory=lambda: list(Defaults.GRAPH_FILE_STOP_WORDS))
    prose_fusion_router_enabled: bool = Defaults.GRAPH_FILE_PROSE_FUSION_ROUTER_ENABLED
    prose_path_weight: float = Defaults.GRAPH_FILE_PROSE_PATH_WEIGHT
    prose_symbol_weight: float = Defaults.GRAPH_FILE_PROSE_SYMBOL_WEIGHT
