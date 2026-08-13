from __future__ import annotations

from typing import Any

from ..config import AppConfig
from .retrieval_strategy_factory import RetrievalStrategyFactory


def make_retrieval_strategy(config: AppConfig, provider: Any, vector_store: Any):
    return RetrievalStrategyFactory().create(
        config.search.strategy, config, provider, vector_store
    )
