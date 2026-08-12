from __future__ import annotations

import os

from ..settings import Defaults, EmbeddingProviderId, EnvironmentVariable
from .gemini_embedding_provider import GeminiEmbeddingProvider


class VertexEmbeddingProvider(GeminiEmbeddingProvider):
    def __init__(
        self,
        model: str = Defaults.EMBEDDING_MODEL,
        dimensions: int = Defaults.EMBEDDING_DIMENSIONS,
        api_key: str | None = None,
        project: str | None = None,
        location: str | None = None,
        batch_size: int = 32,
        retry_attempts: int = Defaults.EMBEDDING_RETRY_ATTEMPTS,
        retry_delay_seconds: float = Defaults.EMBEDDING_RETRY_DELAY_SECONDS,
    ):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install the Vertex/Gemini extra with `uv sync --extra gemini` before using Vertex embeddings.") from exc

        self.name = EmbeddingProviderId.VERTEX.value
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.project = project or os.environ.get(EnvironmentVariable.GOOGLE_CLOUD_PROJECT.value)
        self.location = (
            location
            or os.environ.get(EnvironmentVariable.GOOGLE_CLOUD_LOCATION.value)
            or Defaults.VERTEX_LOCATION
        )
        client_kwargs = {"vertexai": True}
        if api_key:
            client_kwargs["api_key"] = api_key
        else:
            client_kwargs["project"] = self.project
            client_kwargs["location"] = self.location
        self.client = genai.Client(**client_kwargs)
        self.types = types

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return super().embed_documents(texts)
