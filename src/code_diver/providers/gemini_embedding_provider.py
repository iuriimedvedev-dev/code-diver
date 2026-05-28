from __future__ import annotations

import os
from typing import Iterable

from .embedding_provider import EmbeddingProvider


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model: str = "gemini-embedding-2",
        dimensions: int = 768,
        api_key: str | None = None,
        batch_size: int = 32,
    ):
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install dependencies with `uv sync` before using Gemini embeddings.") from exc

        self.name = "gemini"
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.client = genai.Client(api_key=resolved_key) if resolved_key else genai.Client()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, self.batch_size):
            result = self.client.models.embed_content(
                model=self.model,
                contents=list(batch),
                config={"output_dimensionality": self.dimensions},
            )
            vectors.extend(_extract_vectors(result.embeddings))
        return vectors

    def embed_query(self, query: str) -> list[float]:
        result = self.client.models.embed_content(
            model=self.model,
            contents=f"task: code retrieval | query: {query}",
            config={"output_dimensionality": self.dimensions},
        )
        vectors = _extract_vectors(result.embeddings)
        if not vectors:
            raise RuntimeError("Gemini returned no query embedding.")
        return vectors[0]


def _extract_vectors(embeddings: Iterable[object]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for embedding in embeddings:
        values = getattr(embedding, "values", embedding)
        vectors.append([float(value) for value in values])
    return vectors


def _batches(items: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]
