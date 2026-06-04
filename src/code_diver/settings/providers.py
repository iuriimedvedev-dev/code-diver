from __future__ import annotations

from enum import StrEnum


class EmbeddingProviderId(StrEnum):
    GEMINI = "gemini"
    HASH = "hash"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    VERTEX = "vertex"


class VectorStoreProviderId(StrEnum):
    JSON = "json"
    QDRANT = "qdrant"
