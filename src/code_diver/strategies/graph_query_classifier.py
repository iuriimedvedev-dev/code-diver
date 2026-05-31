from __future__ import annotations

from ..config import HybridSearchConfig
from .hybrid_query_analyzer import HybridQueryAnalyzer
from .hybrid_query_router import HybridQueryRouter


class GraphQueryClassifier:
    def __init__(self):
        self.config = HybridSearchConfig(routing_enabled=True)
        self.analyzer = HybridQueryAnalyzer(self.config)
        self.router = HybridQueryRouter()

    def classify(self, query: str) -> str:
        profile = self.analyzer.analyze(query)
        return self.router.route_name(query, profile.terms)
