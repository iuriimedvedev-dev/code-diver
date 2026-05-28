from __future__ import annotations

from ..config import AppConfig
from .json_vector_store import JsonVectorStore
from .qdrant_vector_store import QdrantVectorStore
from .vector_store import VectorStore


def create_vector_store(config: AppConfig) -> VectorStore:
    storage = config.storage or {}
    provider = str(storage.get("provider", "json"))
    if provider == "json":
        return JsonVectorStore(config.artifact)
    if provider == "qdrant":
        qdrant = dict(storage.get("qdrant") or {})
        return QdrantVectorStore(
            url=str(qdrant.get("url", "http://localhost:6333")),
            location=qdrant.get("location"),
            collection=str(qdrant.get("collection", "code_diver")),
            api_key=qdrant.get("api_key"),
            api_key_env=qdrant.get("api_key_env", "QDRANT_API_KEY"),
            batch_size=int(qdrant.get("batch_size", 64)),
        )
    raise ValueError(f"Unknown vector store provider: {provider}")
