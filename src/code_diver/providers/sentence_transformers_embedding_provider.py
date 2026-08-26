from __future__ import annotations

import logging
from typing import Any

from ..services.embedding_text_preparer import truncate_embedding_text
from ..settings import Defaults, EmbeddingProviderId
from .embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)


class SentenceTransformersEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model: str,
        dimensions: int | None = None,
        batch_size: int = Defaults.EMBEDDING_BATCH_SIZE,
        document_prefix: str | None = Defaults.EMBEDDING_DOCUMENT_PREFIX,
        query_prefix: str | None = Defaults.EMBEDDING_QUERY_PREFIX,
        max_input_chars: int | None = Defaults.EMBEDDING_MAX_INPUT_CHARS,
    ):
        self.name = EmbeddingProviderId.SENTENCE_TRANSFORMERS.value
        self.model = model
        self.dimensions = int(dimensions or 0)
        self.batch_size = batch_size
        self.document_prefix = document_prefix
        self.query_prefix = query_prefix
        self.max_input_chars = max_input_chars
        self._model: Any | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batches(texts, self.batch_size):
            vectors.extend(
                self._embed_with_context_retry(
                    [self._bounded_prefixed(self.document_prefix, text) for text in batch]
                )
            )
        return vectors

    def embed_query(self, query: str) -> list[float]:
        vectors = self._embed_with_context_retry([self._bounded_prefixed(self.query_prefix, query)])
        if not vectors:
            raise RuntimeError("SentenceTransformers returned no query embedding.")
        return vectors[0]

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(
                    "Install SentenceTransformers support with "
                    "`uv sync --group runtime-sentence-transformers`."
                ) from exc
            self._model = SentenceTransformer(self.model)
        return self._model

    def _bounded_prefixed(self, prefix: str | None, text: str) -> str:
        value = f"{prefix}{text}" if prefix else text
        if self.max_input_chars is None or self.max_input_chars <= 0:
            return value
        return truncate_embedding_text(
            value,
            self.max_input_chars,
            getattr(self._load_model(), "tokenizer", None),
        )

    def _embed_with_context_retry(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._embed(texts)
        except Exception as exc:
            if not _is_context_overflow(exc):
                raise
            if len(texts) == 1:
                current = texts[0]
                for attempt in range(1, 4):
                    current = current[: max(len(current) // 2, 1)]
                    logger.warning(
                        "Embedding input exceeded context; retrying item with %d characters (attempt %d/3).",
                        len(current),
                        attempt,
                    )
                    try:
                        return self._embed([current])
                    except Exception as retry_exc:
                        if not _is_context_overflow(retry_exc) or attempt == 3:
                            raise
                raise RuntimeError("Embedding context retry failed.")
            vectors: list[list[float]] = []
            for text in texts:
                vectors.extend(self._embed_with_context_retry([text]))
            return vectors

    def _embed(self, texts: list[str]) -> list[list[float]]:
        encoded = self._load_model().encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vectors = [[float(value) for value in row] for row in encoded.tolist()]
        if vectors and not self.dimensions:
            self.dimensions = len(vectors[0])
        if vectors and self.dimensions and len(vectors[0]) != self.dimensions:
            raise RuntimeError(
                f"SentenceTransformers embedding dimension mismatch: expected {self.dimensions}, "
                f"got {len(vectors[0])}."
            )
        return vectors


def _batches(items: list[str], size: int):
    for offset in range(0, len(items), max(size, 1)):
        yield items[offset : offset + max(size, 1)]


def _is_context_overflow(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in ("context length", "maximum context", "input too long", "too many tokens", "sequence length"))
