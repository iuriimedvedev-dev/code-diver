from __future__ import annotations

from .embedding_provider import EmbeddingProvider
from .gemini_embedding_provider import GeminiEmbeddingProvider
from .hash_embedding_provider import HashEmbeddingProvider


def create_embedding_provider(
    provider: str,
    model: str | None = None,
    dimensions: int | None = None,
    api_key: str | None = None,
    batch_size: int = 32,
) -> EmbeddingProvider:
    if provider == "hash":
        return HashEmbeddingProvider(dimensions=dimensions or 256)
    if provider == "gemini":
        return GeminiEmbeddingProvider(
            model=model or "gemini-embedding-2",
            dimensions=dimensions or 768,
            api_key=api_key,
            batch_size=batch_size,
        )
    raise ValueError(f"Unknown embedding provider: {provider}")
