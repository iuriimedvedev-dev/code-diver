from __future__ import annotations

import re
from dataclasses import replace

from ..config import HybridSearchConfig
from ..services.tokenizer import tokenize

PATH_RE = re.compile(r"[/\\]|(?:^|\s)[A-Za-z0-9_-]+\.(py|ts|tsx|js|json|ya?ml|toml|md|sh)\b")
IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:[A-Z_][A-Za-z0-9_]*)\b")
LEXICAL_SCORING_BM25 = "bm25"
ROUTE_PATH_SYMBOL = "path_symbol"
ROUTE_SEMANTIC = "semantic"
ROUTE_WORKFLOW = "workflow"

PATH_TERMS = {
    "docker",
    "compose",
    "config",
    "configured",
    "package",
    "dependencies",
    "scripts",
    "pyproject",
    "frontend",
    "npm",
    "yaml",
    "settings",
}
SYMBOL_TERMS = {
    "class",
    "function",
    "method",
    "interface",
    "model",
    "schema",
    "agent",
    "operator",
    "service",
    "repository",
}
WORKFLOW_TERMS = {
    "called",
    "call",
    "run",
    "created",
    "registered",
    "resolved",
    "dispatch",
    "handler",
    "route",
    "endpoint",
    "workflow",
    "pipeline",
    "strategy",
    "orchestrated",
    "execution",
}
RAW_WORKFLOW_TERMS = WORKFLOW_TERMS | {
    "calls",
    "construct",
    "constructed",
    "constructs",
    "create",
    "created",
    "creates",
    "dispatched",
    "dispatches",
    "generated",
    "included",
    "managed",
    "orchestrate",
    "orchestrates",
    "persisted",
    "resolves",
    "runs",
    "setup",
    "stored",
    "wrap",
    "wraps",
}


class HybridQueryRouter:
    def route(self, query: str, terms: tuple[str, ...], config: HybridSearchConfig) -> HybridSearchConfig:
        if not config.routing_enabled:
            return config
        route_name = self.route_name(query, terms)
        if route_name == ROUTE_WORKFLOW:
            return replace(
                config,
                vector_weight=0.52,
                lexical_weight=0.15,
                path_weight=0.1,
                symbol_weight=0.05,
                graph_weight=0.1,
                graph_depth=max(config.graph_depth, 2),
                graph_neighbor_limit=max(config.graph_neighbor_limit, 30),
            )
        if route_name == ROUTE_PATH_SYMBOL:
            return replace(
                config,
                lexical_scoring=LEXICAL_SCORING_BM25,
                fusion="weighted",
                lexical_candidate_limit=max(config.lexical_candidate_limit, 160),
                vector_weight=0.45,
                lexical_weight=max(config.lexical_weight + 0.08, 0.25),
                path_weight=max(config.path_weight + 0.08, 0.2),
                symbol_weight=0.08,
                graph_weight=0.02,
            )
        if route_name == ROUTE_SEMANTIC:
            return replace(
                config,
                graph_weight=min(config.graph_weight, 0.01),
                graph_depth=min(config.graph_depth, 1),
                graph_neighbor_limit=min(config.graph_neighbor_limit, 16),
            )
        return config

    def route_name(self, query: str, terms: tuple[str, ...]) -> str:
        term_set = set(terms)
        if self._workflow_query(query, term_set):
            return ROUTE_WORKFLOW
        if self._path_or_symbol_query(query, term_set):
            return ROUTE_PATH_SYMBOL
        return ROUTE_SEMANTIC

    def _workflow_query(self, query: str, terms: set[str]) -> bool:
        raw_terms = set(tokenize(query))
        return bool(terms & WORKFLOW_TERMS) or bool(raw_terms & RAW_WORKFLOW_TERMS)

    def _path_or_symbol_query(self, query: str, terms: set[str]) -> bool:
        return bool(PATH_RE.search(query)) or bool(terms & PATH_TERMS) or bool(terms & SYMBOL_TERMS) or self._has_identifier(query)

    def _has_identifier(self, query: str) -> bool:
        return any("_" in match or any(char.isupper() for char in match[1:]) for match in IDENTIFIER_RE.findall(query))
