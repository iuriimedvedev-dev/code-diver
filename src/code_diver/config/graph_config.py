from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Defaults


@dataclass(slots=True)
class GraphConfig:
    enabled: bool = True
    artifact: Path = Defaults.GRAPH_ARTIFACT
    expansion_depth: int = Defaults.GRAPH_EXPANSION_DEPTH
    neighbor_limit: int = Defaults.GRAPH_NEIGHBOR_LIMIT
    ast_enabled: bool = Defaults.GRAPH_AST_ENABLED
    reference_edges_enabled: bool = Defaults.GRAPH_REFERENCE_EDGES_ENABLED
    call_edges_enabled: bool = Defaults.GRAPH_CALL_EDGES_ENABLED
