from __future__ import annotations

import os
import time
from collections.abc import Iterable

from ..settings import Defaults, EmbeddingProviderId, EnvironmentVariable
from .embedding_provider import EmbeddingProvider


class GeminiEmbeddingProvider(EmbeddingProvider):
    DOCUMENT_PREFIX = "Task: retrieve relevant codebase context.\nDocument:"
    QUERY_PREFIX = "Task: retrieve codebase documents relevant to this question.\nQuery:"

    def __init__(
        self,
        model: str = Defaults.EMBEDDING_MODEL,
        dimensions: int = Defaults.EMBEDDING_DIMENSIONS,
        api_key: str | None = None,
        batch_size: int = 32,
        retry_attempts: int = Defaults.EMBEDDING_RETRY_ATTEMPTS,
        retry_delay_seconds: float = Defaults.EMBEDDING_RETRY_DELAY_SECONDS,
    ):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Install the Vertex/Gemini extra with `uv sync --extra gemini` before using Gemini embeddings.") from exc

        self.name = EmbeddingProviderId.GEMINI.value
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        resolved_key = api_key or os.environ.get(EnvironmentVariable.GEMINI_API_KEY.value)
        self.client = genai.Client(api_key=resolved_key) if resolved_key else genai.Client()
        self.types = types

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, self.batch_size):
            contents = self._document_contents(list(batch))
            result = self._embed_with_retry(contents, "RETRIEVAL_DOCUMENT")
            vectors.extend(_extract_vectors(result.embeddings))
        return vectors

    def embed_query(self, query: str) -> list[float]:
        result = self._embed_with_retry(self._query_content(query), "CODE_RETRIEVAL_QUERY")
        vectors = _extract_vectors(result.embeddings)
        if not vectors:
            raise RuntimeError("Gemini returned no query embedding.")
        return vectors[0]

    def _embed_with_retry(self, contents: object, task_type: str):
        last_error: Exception | None = None
        for attempt in range(max(self.retry_attempts, 1)):
            try:
                config_kwargs = {"output_dimensionality": self.dimensions}
                if not self._uses_embedding_2():
                    config_kwargs["task_type"] = task_type
                return self.client.models.embed_content(
                    model=self.model,
                    contents=contents,
                    config=self.types.EmbedContentConfig(**config_kwargs),
                )
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= max(self.retry_attempts, 1):
                    break
                time.sleep(self.retry_delay_seconds * (attempt + 1))
        raise last_error or RuntimeError("Gemini embedding request failed.")

    def _document_contents(self, texts: list[str]) -> object:
        if not self._uses_embedding_2():
            return texts
        return [self._content(f"{self.DOCUMENT_PREFIX}\n{text}") for text in texts]

    def _query_content(self, query: str) -> object:
        if not self._uses_embedding_2():
            return query
        return self._content(f"{self.QUERY_PREFIX}\n{query}")

    def _content(self, text: str):
        return self.types.Content(parts=[self.types.Part.from_text(text=text)])

    def _uses_embedding_2(self) -> bool:
        return self.model == "gemini-embedding-2"


def _extract_vectors(embeddings: Iterable[object]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for embedding in embeddings:
        values = getattr(embedding, "values", embedding)
        vectors.append([float(value) for value in values])
    return vectors


def _batches(items: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]
