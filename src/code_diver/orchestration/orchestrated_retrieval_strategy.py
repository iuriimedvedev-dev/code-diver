from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ..domain import SearchResult
from ..generation import GenerationProvider
from ..store import VectorStore
from ..tracing import TraceLogger
from .query_plan_orchestrator import QueryPlanOrchestrator

if TYPE_CHECKING:
    from ..strategies.retrieval_strategy import RetrievalStrategy


class OrchestratedRetrievalStrategy:
    def __init__(
        self,
        base_strategy: RetrievalStrategy,
        vector_store: VectorStore,
        generation_provider: GenerationProvider,
        per_query_limit: int = 10,
        trace_logger: TraceLogger | None = None,
    ):
        self.base_strategy = base_strategy
        self.vector_store = vector_store
        self.generation_provider = generation_provider
        self.per_query_limit = per_query_limit
        self.trace_logger = trace_logger or TraceLogger.disabled()

    def search(self, query: str, limit: int) -> list[SearchResult]:
        plan = QueryPlanOrchestrator(self.generation_provider, self.trace_logger).plan(query, self.vector_store.metadata())
        scores: dict[str, float] = defaultdict(float)
        items: dict[str, object] = {}
        for variant in plan.queries[:5]:
            for result in self.base_strategy.search(variant, max(limit, self.per_query_limit)):
                items[result.item.id] = result.item
                scores[result.item.id] = max(scores[result.item.id], result.score)
        results = [SearchResult(item=item, score=scores[item_id]) for item_id, item in items.items()]
        results.sort(key=lambda result: result.score, reverse=True)
        self.trace_logger.write(
            "orchestrated_search_results",
            {
                "query": query,
                "variants": plan.queries[:5],
                "candidate_count": len(results),
                "returned": [result.item.id for result in results[:limit]],
            },
        )
        return results[:limit]
