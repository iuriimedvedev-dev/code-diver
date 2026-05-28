from __future__ import annotations

from dataclasses import dataclass, field

from ..settings import Defaults


@dataclass(slots=True)
class AiIndexConfig:
    max_files: int = Defaults.AI_INDEX_MAX_FILES
    max_items: int = Defaults.AI_INDEX_MAX_ITEMS
    max_context_chars: int = Defaults.AI_INDEX_MAX_CONTEXT_CHARS
    tree_depth: int = Defaults.AI_INDEX_TREE_DEPTH
    tree_limit: int = Defaults.AI_INDEX_TREE_LIMIT
    discovery_limit: int = Defaults.AI_INDEX_DISCOVERY_LIMIT
    discovery_patterns: list[str] = field(default_factory=lambda: list(Defaults.AI_INDEX_DISCOVERY_PATTERNS))
