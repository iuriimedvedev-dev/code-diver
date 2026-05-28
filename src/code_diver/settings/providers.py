from __future__ import annotations

from enum import StrEnum


class EmbeddingProviderId(StrEnum):
    GEMINI = "gemini"
    HASH = "hash"
    OPENAI = "openai"


class VectorStoreProviderId(StrEnum):
    JSON = "json"
    QDRANT = "qdrant"
