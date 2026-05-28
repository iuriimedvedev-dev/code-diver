from __future__ import annotations

from ..config import AppConfig
from ..settings import VectorStoreProviderId
from .json_vector_store import JsonVectorStore
from .qdrant_vector_store import QdrantVectorStore
from .vector_store import VectorStore


def create_vector_store(config: AppConfig) -> VectorStore:
    provider = VectorStoreProviderId(config.storage.provider)
    if provider is VectorStoreProviderId.JSON:
        return JsonVectorStore(config.artifact)
    if provider is VectorStoreProviderId.QDRANT:
        qdrant = config.storage.qdrant
        return QdrantVectorStore(
            url=qdrant.url,
            location=qdrant.location,
            collection=qdrant.collection,
            api_key=qdrant.api_key,
            api_key_env=qdrant.api_key_env,
            batch_size=qdrant.batch_size,
        )
    raise ValueError(f"Unknown vector store provider: {provider}")
