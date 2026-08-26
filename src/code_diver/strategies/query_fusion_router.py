from __future__ import annotations

import re
from dataclasses import replace

from ..config import GraphFileSearchConfig, HybridSearchConfig
from ..services.tokenizer import tokenize
from .hybrid_query_router import (
    IDENTIFIER_RE,
    PATH_RE,
    PATH_TERMS,
    SYMBOL_TERMS,
    HybridQueryRouter,
)

DOTTED_PATH_RE = re.compile(r"\b[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+\b")
PROSE_VERBS = frozenset({"where", "how", "find", "which", "what"})
QUERY_KIND_IDENTIFIER = "identifier"
QUERY_KIND_PROSE = "prose"


class QueryFusionRouter:
    """Downweight path/symbol fusion for prose WHERE queries. Default off via config."""

    def __init__(self) -> None:
        self._hybrid_router = HybridQueryRouter()

    def classify(self, query: str) -> str:
        if self.is_identifier_like(query):
            return QUERY_KIND_IDENTIFIER
        if self.is_prose_where(query):
            return QUERY_KIND_PROSE
        return QUERY_KIND_IDENTIFIER

    def is_identifier_like(self, query: str) -> bool:
        tokens = set(tokenize(query))
        if PATH_RE.search(query) or DOTTED_PATH_RE.search(query):
            return True
        if self._hybrid_router._has_identifier(query):
            return True
        if IDENTIFIER_RE.search(query) and any(ch.isupper() for ch in query):
            return True
        if tokens & PATH_TERMS or tokens & SYMBOL_TERMS:
            return True
        return False

    def is_prose_where(self, query: str) -> bool:
        if self.is_identifier_like(query):
            return False
        tokens = set(tokenize(query))
        if tokens & PROSE_VERBS:
            return True
        words = [part for part in re.findall(r"[A-Za-z]+", query) if part]
        if not words:
            return False
        identifier_hits = sum(1 for word in words if word[:1].isupper() or "_" in word or "." in word)
        return identifier_hits == 0 and len(words) >= 3

    def apply_hybrid(self, query: str, config: HybridSearchConfig) -> HybridSearchConfig:
        if not config.prose_fusion_router_enabled:
            return config
        if self.classify(query) != QUERY_KIND_PROSE:
            return config
        return self._redistribute_hybrid(config)

    def apply_graph_file(self, query: str, config: GraphFileSearchConfig) -> GraphFileSearchConfig:
        if not config.prose_fusion_router_enabled:
            return config
        if self.classify(query) != QUERY_KIND_PROSE:
            return config
        return self._redistribute_graph_file(config)

    def _redistribute_hybrid(self, config: HybridSearchConfig) -> HybridSearchConfig:
        extra = max(0.0, config.path_weight - config.prose_path_weight) + max(
            0.0, config.symbol_weight - config.prose_symbol_weight
        )
        share = extra / 2.0
        return replace(
            config,
            path_weight=min(config.path_weight, config.prose_path_weight),
            symbol_weight=min(config.symbol_weight, config.prose_symbol_weight),
            vector_weight=config.vector_weight + share,
            lexical_weight=config.lexical_weight + share,
        )

    def _redistribute_graph_file(self, config: GraphFileSearchConfig) -> GraphFileSearchConfig:
        extra = max(0.0, config.path_weight - config.prose_path_weight) + max(
            0.0, config.symbol_weight - config.prose_symbol_weight
        )
        share = extra / 2.0
        return replace(
            config,
            path_weight=min(config.path_weight, config.prose_path_weight),
            symbol_weight=min(config.symbol_weight, config.prose_symbol_weight),
            vector_weight=config.vector_weight + share,
            lexical_weight=config.lexical_weight + share,
        )
