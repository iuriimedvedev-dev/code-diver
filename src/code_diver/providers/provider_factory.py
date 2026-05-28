from __future__ import annotations

from ..settings import Defaults, EmbeddingProviderId
from .embedding_provider import EmbeddingProvider
from .gemini_embedding_provider import GeminiEmbeddingProvider
from .hash_embedding_provider import HashEmbeddingProvider
from .openai_compatible_embedding_provider import OpenAICompatibleEmbeddingProvider
from .openai_embedding_provider import OpenAIEmbeddingProvider


def create_embedding_provider(
    provider: str,
    model: str | None = None,
    dimensions: int | None = None,
    api_key: str | None = None,
    url: str | None = None,
    batch_size: int = 32,
    retry_attempts: int = Defaults.EMBEDDING_RETRY_ATTEMPTS,
    retry_delay_seconds: float = Defaults.EMBEDDING_RETRY_DELAY_SECONDS,
) -> EmbeddingProvider:
    provider_id = EmbeddingProviderId(provider)
    if provider_id is EmbeddingProviderId.HASH:
        return HashEmbeddingProvider(dimensions=dimensions or Defaults.HASH_DIMENSIONS)
    if provider_id is EmbeddingProviderId.GEMINI:
        return GeminiEmbeddingProvider(
            model=model or Defaults.EMBEDDING_MODEL,
            dimensions=dimensions or Defaults.EMBEDDING_DIMENSIONS,
            api_key=api_key,
            batch_size=batch_size,
            retry_attempts=retry_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
    if provider_id is EmbeddingProviderId.OPENAI:
        return OpenAIEmbeddingProvider(
            model=model or Defaults.OPENAI_EMBEDDING_MODEL,
            dimensions=dimensions or Defaults.OPENAI_EMBEDDING_DIMENSIONS,
            api_key=api_key,
            url=url or Defaults.OPENAI_EMBEDDINGS_URL,
            batch_size=batch_size,
        )
    if provider_id is EmbeddingProviderId.OPENAI_COMPATIBLE:
        return OpenAICompatibleEmbeddingProvider(
            model=model or "nomic-embed-text",
            dimensions=dimensions,
            api_key=api_key,
            url=url,
            batch_size=batch_size,
        )
    raise ValueError(f"Unknown embedding provider: {provider}")
