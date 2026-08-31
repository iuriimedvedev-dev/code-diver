from __future__ import annotations

from contextlib import suppress
from typing import Any

from ..agent.h3_search_tool_handler import H3SearchToolHandler
from ..config import AppConfig
from ..inspection.exclude_patterns import inspection_exclude_patterns
from ..reranking import RerankProviderFactory
from ..store import create_vector_store
from ..strategies import RetrievalStrategyFactory
from ..strategies.fan_out_union_rerank_search import FanOutUnionRerankSearch


class SearchRuntime:
    """Per-hypothesis search dependency graph with lazy, reusable components."""

    def __init__(self, config: AppConfig, *, fan_out_fusion: Any = None) -> None:
        self.config = config
        self.fan_out_fusion = fan_out_fusion
        self._vector_store: Any | None = None
        self._provider: Any | None = None
        self._base_strategy: Any | None = None
        self._graph_file_strategy: Any | None = None
        self._rerank_provider: Any | None = None
        self._fan_out_handler: Any | None = None
        self._h3_handler: H3SearchToolHandler | None = None

    @property
    def vector_store(self) -> Any:
        if self._vector_store is None:
            self._vector_store = create_vector_store(self.config)
        return self._vector_store

    @property
    def embedding_provider(self) -> Any:
        if self._provider is None:
            from ..providers.embedding_provider_builder import make_embedding_provider

            self._provider = make_embedding_provider(self.config, self.vector_store.metadata())
        return self._provider

    @property
    def provider(self) -> Any:
        return self.embedding_provider

    @property
    def graph_file_strategy(self) -> Any:
        if self._graph_file_strategy is None:
            self._graph_file_strategy = RetrievalStrategyFactory().create(
                "graph_file", self.config, self.embedding_provider, self.vector_store
            )
        return self._graph_file_strategy

    @property
    def base_strategy(self) -> Any:
        if self.config.search.strategy == "graph_file":
            return self.graph_file_strategy
        if self._base_strategy is None:
            self._base_strategy = RetrievalStrategyFactory().create(
                self.config.search.strategy, self.config, self.embedding_provider, self.vector_store
            )
        return self._base_strategy

    @property
    def fan_out_union_handler(self):
        settings = self.fan_out_fusion
        if self._fan_out_handler is None and settings is not None and settings.enabled and settings.union_rerank:
            workers = int(getattr(settings, "max_probe_workers", 6) or 6)
            parallel = bool(getattr(settings, "parallel_probes", True))
            search = FanOutUnionRerankSearch(
                self.graph_file_strategy,
                self.rerank_provider,
                self.config.cross_encoder_rerank,
                repository_root=self.config.root,
                max_workers=workers if parallel else 1,
                union_candidate_limit=settings.union_candidate_limit,
                parallel_probes=parallel,
            )
            self._fan_out_handler = search.paths
        return self._fan_out_handler

    @property
    def rerank_provider(self) -> Any:
        if self._rerank_provider is None:
            self._rerank_provider = RerankProviderFactory().create(self.config.cross_encoder_rerank)
        return self._rerank_provider

    @property
    def fan_out_handler(self):
        return self.fan_out_union_handler

    @property
    def h3_search_handler(self):
        if self._h3_handler is None:
            self._h3_handler = H3SearchToolHandler(
                self.config,
                self.embedding_provider,
                self.vector_store,
                exclude=inspection_exclude_patterns(self.config),
            )
        return self._h3_handler.search

    @property
    def h3_handler(self):
        return self.h3_search_handler

    def warm(self, query: str = "warm up search runtime", limit: int = 10) -> None:
        """Build clients once and force graph catalog + lexical index load.

        Subsequent queries reuse process-level strategy caches; call before timed work.
        """
        if getattr(self, "_warmed", False):
            return
        strategy = self.graph_file_strategy
        _ = self.base_strategy
        _ = self.embedding_provider
        _ = self.vector_store
        with suppress(Exception):
            strategy.search(query, max(1, limit))
        if self.fan_out_fusion is not None and self.fan_out_fusion.enabled and self.fan_out_fusion.union_rerank:
            _ = self.rerank_provider
        _ = self.h3_search_handler
        _ = self.fan_out_union_handler
        self._warmed = True

    def close(self) -> None:
        close = getattr(self._vector_store, "close", None)
        if callable(close):
            close()
        self._vector_store = None
