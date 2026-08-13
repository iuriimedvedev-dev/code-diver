from __future__ import annotations

from typing import Any

from ..config import AppConfig
from ..generation.generation_provider_factory import create_generation_provider
from .repository_context_builder import RepositoryContextBuilder
from .repository_readme_summarizer import RepositoryReadmeSummarizer


def build_repository_context(
    config: AppConfig,
    generation_provider: Any | None = None,
) -> Any:
    summarizer = None
    if config.pi.repo_context.mode == "llm_readme_summary":
        provider = generation_provider or create_generation_provider(config)
        summarizer = RepositoryReadmeSummarizer(provider).summarize
    return RepositoryContextBuilder().build(config, readme_summarizer=summarizer)
