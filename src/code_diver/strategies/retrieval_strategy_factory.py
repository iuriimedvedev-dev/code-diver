from __future__ import annotations

from ..config import AppConfig
from ..config.rerank_generation_config import rerank_generation_config
from ..generation import create_generation_provider
from ..graph import CodeGraphStore
from ..orchestration import OrchestratedRetrievalStrategy
from ..providers import EmbeddingProvider
from ..reranking import RerankProviderFactory
from ..settings import RetrievalStrategyId
from ..store import VectorStore
from ..store.qdrant_vector_store import QdrantVectorStore
from ..tracing import TraceLogger
from .cross_encoder_rerank_retrieval_strategy import CrossEncoderRerankRetrievalStrategy
from .dual_collection_vector_retrieval_strategy import DualCollectionVectorRetrievalStrategy
from .graph_file_retrieval_strategy import GraphFileRetrievalStrategy
from .graph_retrieval_strategy import GraphRetrievalStrategy
from .hybrid_retrieval_strategy import HybridRetrievalStrategy
from .llm_rerank_retrieval_strategy import LlmRerankRetrievalStrategy
from .multi_index_vector_retrieval_strategy import MultiIndexVectorRetrievalStrategy
from .multi_query_rrf_strategy import LlmQueryRewriter, MultiQueryRrfStrategy
from .recursive_retrieval_strategy import RecursiveRetrievalStrategy
from .retrieval_strategy import RetrievalStrategy
from .vector_retrieval_strategy import VectorRetrievalStrategy


class RetrievalStrategyFactory:
    def _create_base(
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
        if strategy_id is RetrievalStrategyId.GRAPH_FILE:
            return self._create_graph_file_base(config, provider, vector_store)
        if strategy_id is RetrievalStrategyId.GRAPH_FILE_RERANK:
            return LlmRerankRetrievalStrategy(
                self._graph_file_strategy(config, provider, vector_store),
                create_generation_provider(self._rerank_generation_config(config)),
                config.llm_rerank,
                trace_logger=TraceLogger(config.trace),
            )
        if strategy_id is RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER:
            # Same base as GRAPH_FILE_RERANK, different rerank primitive. The existing
            # CROSS_ENCODER_RERANK sits on plain hybrid, so swapping to it from the champion
            # would change the base *and* the reranker and leave neither attributable.
            return self._cross_encoder_strategy(self._create_graph_file_base(config, provider, vector_store), config)
        if strategy_id is RetrievalStrategyId.HYBRID:
            return self._hybrid_strategy(config, provider, vector_store)
        if strategy_id is RetrievalStrategyId.HYBRID_RERANK:
            hybrid = self._hybrid_strategy(config, provider, vector_store)
            return LlmRerankRetrievalStrategy(
                hybrid,
                create_generation_provider(self._rerank_generation_config(config)),
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
                repository_root=config.root,
            )
        raise ValueError(f"Unknown retrieval strategy: {strategy}")

    def _create_graph_file_base(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        return GraphFileRetrievalStrategy(
            HybridRetrievalStrategy(
                self._hybrid_vector_strategy(config, provider, vector_store),
                CodeGraphStore(config.graph.artifact),
                config.hybrid_search,
                trace_logger=TraceLogger(config.trace),
            ),
            CodeGraphStore(config.graph.artifact),
            config.graph_file_search,
        )

    def create(
        self,
        strategy: str,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        if not config.multi_query.enabled:
            return self._create_base(strategy, config, provider, vector_store)
        rewriter = LlmQueryRewriter(create_generation_provider(config)) if config.multi_query.llm_rewrites_enabled else None
        strategy_id = RetrievalStrategyId(strategy)
        if getattr(config.multi_query, "union_rerank", False) and strategy_id is RetrievalStrategyId.GRAPH_FILE_CROSS_ENCODER:
            pre_ce = MultiQueryRrfStrategy(
                self._create_graph_file_base(config, provider, vector_store),
                config.multi_query,
                llm_rewriter=rewriter,
                fusion_pool_size=config.cross_encoder_rerank.candidate_limit,
            )
            return self._cross_encoder_strategy(pre_ce, config)
        base = self._create_base(strategy, config, provider, vector_store)
        return MultiQueryRrfStrategy(base, config.multi_query, llm_rewriter=rewriter)

    def _cross_encoder_strategy(self, base: RetrievalStrategy, config: AppConfig) -> RetrievalStrategy:
        return CrossEncoderRerankRetrievalStrategy(
            base,
            RerankProviderFactory().create(config.cross_encoder_rerank),
            config.cross_encoder_rerank,
            trace_logger=TraceLogger(config.trace),
            repository_root=config.root,
        )

    def _rerank_generation_config(self, config: AppConfig) -> AppConfig:
        """Swap in `llm_rerank.generation` so the rerank stage can run its own model."""
        return rerank_generation_config(config)

    def _hybrid_vector_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        primary = self._single_vector_strategy(config, provider, vector_store)
        secondary_collection = (config.hybrid_search.secondary_collection or "").strip()
        if not secondary_collection:
            return primary
        secondary_store = self._secondary_vector_store(config, secondary_collection)
        secondary = self._single_vector_strategy(config, provider, secondary_store)
        return DualCollectionVectorRetrievalStrategy(
            primary,
            secondary,
            fusion=config.hybrid_search.secondary_collection_fusion,
            rrf_k=config.hybrid_search.secondary_collection_rrf_k,
        )

    def _single_vector_strategy(
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
                config.hybrid_search.vector_kind_path_dedup,
            )
        return VectorRetrievalStrategy(provider, vector_store)

    def _secondary_vector_store(self, config: AppConfig, collection: str) -> VectorStore:
        qdrant = config.storage.qdrant
        return QdrantVectorStore(
            url=qdrant.url,
            location=qdrant.location,
            collection=collection,
            api_key=qdrant.api_key,
            api_key_env=qdrant.api_key_env,
            batch_size=qdrant.batch_size,
        )

    def _graph_file_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        return GraphFileRetrievalStrategy(
            self._hybrid_strategy(config, provider, vector_store),
            CodeGraphStore(config.graph.artifact),
            config.graph_file_search,
        )

    def _hybrid_strategy(
        self,
        config: AppConfig,
        provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> RetrievalStrategy:
        return HybridRetrievalStrategy(
            self._hybrid_vector_strategy(config, provider, vector_store),
            CodeGraphStore(config.graph.artifact),
            config.hybrid_search,
            trace_logger=TraceLogger(config.trace),
        )
