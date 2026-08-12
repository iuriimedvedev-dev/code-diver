from __future__ import annotations

from dataclasses import replace

from .app_config import AppConfig


def rerank_generation_config(config: AppConfig) -> AppConfig:
    """The app config a rerank stage should generate with.

    `llm_rerank.generation` exists so the rerank stage can run a different model than the answer
    stage. Two call sites need that resolution -- the retrieval-strategy wrapper and the answer
    evaluator's final candidate rerank -- and they must resolve it the same way. When only one of
    them honoured the override, a whole arm silently reranked with the answer model and looked
    like a null result (see Finding 35 in .session/2026-08-05_h17-corpus-and-data-loss.md).

    Returns the config unchanged when there is no override, so identity comparison still tells a
    caller whether a separate provider needs building.
    """
    override = config.llm_rerank.generation
    return config if override is None else replace(config, generation=override)
