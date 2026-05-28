from __future__ import annotations

from collections import defaultdict

from ..domain import SearchResult
from ..generation import GenerationProvider
from ..store import VectorStore
from .query_plan_orchestrator import QueryPlanOrchestrator


class OrchestratedRetrievalStrategy:
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        vector_store: VectorStore,
        generation_provider: GenerationProvider,
        per_query_limit: int = 10,
    ):
        self.base_strategy = base_strategy
        self.vector_store = vector_store
        self.generation_provider = generation_provider
        self.per_query_limit = per_query_limit

    def search(self, query: str, limit: int) -> list[SearchResult]:
        plan = QueryPlanOrchestrator(self.generation_provider).plan(query, self.vector_store.metadata())
        scores: dict[str, float] = defaultdict(float)
        items: dict[str, object] = {}
        for variant in plan.queries[:5]:
            for result in self.base_strategy.search(variant, max(limit, self.per_query_limit)):
                items[result.item.id] = result.item
                scores[result.item.id] = max(scores[result.item.id], result.score)
        results = [SearchResult(item=item, score=scores[item_id]) for item_id, item in items.items()]
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]
