from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..generation.transient_generation_retry import TransientGenerationRetry
from ..settings import Defaults, EmbeddingProviderId, EnvironmentVariable
from .embedding_provider import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model: str = Defaults.OPENAI_EMBEDDING_MODEL,
        dimensions: int = Defaults.OPENAI_EMBEDDING_DIMENSIONS,
        api_key: str | None = None,
        batch_size: int = 32,
        url: str = Defaults.OPENAI_EMBEDDINGS_URL,
        timeout_seconds: float = Defaults.OPENAI_TIMEOUT_SECONDS,
        document_prefix: str | None = Defaults.EMBEDDING_DOCUMENT_PREFIX,
        query_prefix: str | None = Defaults.EMBEDDING_QUERY_PREFIX,
        max_input_chars: int | None = Defaults.EMBEDDING_MAX_INPUT_CHARS,
        send_dimensions: bool = True,
        retry_attempts: int = Defaults.EMBEDDING_RETRY_ATTEMPTS,
        retry_delay_seconds: float = Defaults.EMBEDDING_RETRY_DELAY_SECONDS,
    ):
        self.name = EmbeddingProviderId.OPENAI.value
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.document_prefix = document_prefix
        self.query_prefix = query_prefix
        self.max_input_chars = max_input_chars
        self.send_dimensions = send_dimensions
        self.retry = TransientGenerationRetry(
            attempts=retry_attempts,
            base_delay_seconds=retry_delay_seconds,
            max_delay_seconds=max(retry_delay_seconds, 0.0),
        )
        self.api_key = api_key or os.environ.get(EnvironmentVariable.OPENAI_API_KEY.value)
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings.")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, self.batch_size):
            vectors.extend(self._embed([self._bounded_prefixed(self.document_prefix, text) for text in batch]))
        return vectors

    def embed_query(self, query: str) -> list[float]:
        vectors = self._embed([self._bounded_prefixed(self.query_prefix, query)])
        if not vectors:
            raise RuntimeError("OpenAI returned no query embedding.")
        return vectors[0]

    def _prefixed(self, prefix: str | None, text: str) -> str:
        return f"{prefix}{text}" if prefix else text

    def _bounded_prefixed(self, prefix: str | None, text: str) -> str:
        prefixed = self._prefixed(prefix, text)
        if self.max_input_chars is None or self.max_input_chars <= 0:
            return prefixed
        return prefixed[: self.max_input_chars]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        if self.send_dimensions and self.dimensions:
            payload["dimensions"] = self.dimensions
        response = self.retry.run(lambda: self._post(payload))
        rows = sorted(response.get("data", []), key=lambda row: int(row.get("index", 0)))
        return [[float(value) for value in row["embedding"]] for row in rows]

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=self._headers(),
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI embeddings request failed: HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI embeddings API is not reachable: {exc.reason}") from exc

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


def _batches(items: list[str], size: int):
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]
