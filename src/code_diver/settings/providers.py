from __future__ import annotations

from enum import StrEnum


class EmbeddingProviderId(StrEnum):
    GEMINI = "gemini"
    HASH = "hash"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    VERTEX = "vertex"
    LITELLM = "litellm"
    LOCAL = "local"
    JBCENTRAL = "jbcentral"


class GenerationProviderId(StrEnum):
    GEMINI = "gemini"
    GEMINI_CLI = "gemini_cli"
    AGY_CLI = "agy_cli"
    ANTIGRAVITY_SDK = "antigravity_sdk"
    VERTEX = "vertex"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    LITELLM = "litellm"
    LOCAL = "local"
    JBCENTRAL = "jbcentral"


class VectorStoreProviderId(StrEnum):
    JSON = "json"
    QDRANT = "qdrant"
