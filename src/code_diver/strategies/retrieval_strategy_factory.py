from __future__ import annotations

from ..config import AppConfig
from ..graph import CodeGraphStore
from ..generation import create_generation_provider
from ..orchestration import OrchestratedRetrievalStrategy
from ..providers import EmbeddingProvider
from ..settings import RetrievalStrategyId
from ..store import VectorStore
from ..tracing import TraceLogger
from .graph_retrieval_strategy import GraphRetrievalStrategy
from .hybrid_retrieval_strategy import HybridRetrievalStrategy
from .llm_rerank_retrieval_strategy import LlmRerankRetrievalStrategy
from .recursive_retrieval_strategy import RecursiveRetrievalStrategy
from .retrieval_strategy import RetrievalStrategy
from .vector_retrieval_strategy import VectorRetrievalStrategy


class RetrievalStrategyFactory:
    def create(
        self,
        strategy: str,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        strategy_id = RetrievalStrategyId(strategy)
        vector = VectorRetrievalStrategy(provider, vector_store)
        if strategy_id is RetrievalStrategyId.ORCHESTRATED:
            return OrchestratedRetrievalStrategy(
                vector,
                vector_store,
                create_generation_provider(config),
                per_query_limit=config.search.limit,
                trace_logger=TraceLogger(config.trace),
            )
        if strategy_id is RetrievalStrategyId.VECTOR:
            return vector
        if strategy_id is RetrievalStrategyId.RECURSIVE:
            recursive = config.recursive_search
            return RecursiveRetrievalStrategy(
                vector,
                rounds=recursive.rounds,
                branch_limit=recursive.branch_limit,
                per_round_limit=recursive.limit,
            )
        if strategy_id is RetrievalStrategyId.GRAPH:
            graph = config.graph
            return GraphRetrievalStrategy(
                vector,
                CodeGraphStore(graph.artifact),
                expansion_depth=graph.expansion_depth,
                neighbor_limit=graph.neighbor_limit,
            )
        if strategy_id is RetrievalStrategyId.HYBRID:
            return HybridRetrievalStrategy(vector, CodeGraphStore(config.graph.artifact), config.hybrid_search)
        if strategy_id is RetrievalStrategyId.HYBRID_RERANK:
            hybrid = HybridRetrievalStrategy(vector, CodeGraphStore(config.graph.artifact), config.hybrid_search)
            return LlmRerankRetrievalStrategy(
                hybrid,
                create_generation_provider(config),
                candidate_limit=max(config.hybrid_search.candidate_limit, config.search.limit * 3),
                trace_logger=TraceLogger(config.trace),
            )
        raise ValueError(f"Unknown retrieval strategy: {strategy}")
