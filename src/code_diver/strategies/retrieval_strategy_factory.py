from __future__ import annotations

from ..config import AppConfig
from ..graph import CodeGraphStore
from ..generation import create_generation_provider
from ..orchestration import OrchestratedRetrievalStrategy
from ..providers import EmbeddingProvider
from ..reranking import RerankProviderFactory
from ..settings import RetrievalStrategyId
from ..store import VectorStore
from ..tracing import TraceLogger
from .cross_encoder_rerank_retrieval_strategy import CrossEncoderRerankRetrievalStrategy
from .graph_retrieval_strategy import GraphRetrievalStrategy
from .hybrid_retrieval_strategy import HybridRetrievalStrategy
from .llm_rerank_retrieval_strategy import LlmRerankRetrievalStrategy
from .multi_index_vector_retrieval_strategy import MultiIndexVectorRetrievalStrategy
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
            return HybridRetrievalStrategy(
                self._hybrid_vector_strategy(config, provider, vector_store),
                CodeGraphStore(config.graph.artifact),
                config.hybrid_search,
                trace_logger=TraceLogger(config.trace),
            )
        if strategy_id is RetrievalStrategyId.HYBRID_RERANK:
            hybrid = HybridRetrievalStrategy(
                self._hybrid_vector_strategy(config, provider, vector_store),
                CodeGraphStore(config.graph.artifact),
                config.hybrid_search,
                trace_logger=TraceLogger(config.trace),
            )
            return LlmRerankRetrievalStrategy(
                hybrid,
                create_generation_provider(config),
                config.llm_rerank,
                trace_logger=TraceLogger(config.trace),
            )
        if strategy_id is RetrievalStrategyId.CROSS_ENCODER_RERANK:
            hybrid = HybridRetrievalStrategy(
                self._hybrid_vector_strategy(config, provider, vector_store),
                CodeGraphStore(config.graph.artifact),
                config.hybrid_search,
                trace_logger=TraceLogger(config.trace),
            )
            return CrossEncoderRerankRetrievalStrategy(
                hybrid,
                RerankProviderFactory().create(config.cross_encoder_rerank),
                config.cross_encoder_rerank,
                trace_logger=TraceLogger(config.trace),
            )
        raise ValueError(f"Unknown retrieval strategy: {strategy}")

    def _hybrid_vector_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        if config.hybrid_search.vector_kind_limits or config.hybrid_search.vector_kind_multipliers:
            return MultiIndexVectorRetrievalStrategy(
                provider,
                vector_store,
                config.hybrid_search.vector_kind_limits,
                config.hybrid_search.vector_kind_multipliers,
            )
        return VectorRetrievalStrategy(provider, vector_store)
