from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None

from ..generation.transient_generation_retry import TransientGenerationRetry
from ..settings import Defaults, EmbeddingProviderId, EnvironmentVariable
from .embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)


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
        tokenizer: Any | None = None,
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
        self.tokenizer = tokenizer
        self._tiktoken_encoding: Any | None = None
        self._tiktoken_encoding_loaded = False
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
            values = [self._bounded_prefixed(self.document_prefix, text) for text in batch]
            vectors.extend(self._embed_with_context_retry(values))
        return vectors

    def embed_query(self, query: str) -> list[float]:
        vectors = self._embed_with_context_retry([self._bounded_prefixed(self.query_prefix, query)])
        if not vectors:
            raise RuntimeError("OpenAI returned no query embedding.")
        return vectors[0]

    def _prefixed(self, prefix: str | None, text: str) -> str:
        return f"{prefix}{text}" if prefix else text

    def _bounded_prefixed(self, prefix: str | None, text: str) -> str:
        prefixed = self._prefixed(prefix, text)
        if self.max_input_chars is None or self.max_input_chars <= 0:
            return prefixed
        if len(prefixed) <= self.max_input_chars:
            return prefixed
        try:
            if tiktoken is None:
                raise ImportError("tiktoken is unavailable")
            try:
                encoding = tiktoken.encoding_for_model(self.model)
            except Exception:
                encoding = tiktoken.get_encoding("cl100k_base")
            token_ids = encoding.encode(prefixed)
            if len(token_ids) <= self.max_input_chars:
                return prefixed
            return encoding.decode(token_ids[: self.max_input_chars])
        except Exception:
            return prefixed[: self.max_input_chars // 3]

    def _get_tiktoken_encoding(self) -> Any | None:
        if self._tiktoken_encoding_loaded:
            return self._tiktoken_encoding
        self._tiktoken_encoding_loaded = True
        if tiktoken is None:
            return None
        try:
            try:
                self._tiktoken_encoding = tiktoken.encoding_for_model(self.model)
            except KeyError:
                self._tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._tiktoken_encoding = None
        return self._tiktoken_encoding

    def _truncate_with_tokenizer(self, text: str, budget: int) -> str:
        try:
            token_ids = self.tokenizer.encode(text, add_special_tokens=False)
            for count in range(min(len(token_ids), budget), 0, -1):
                try:
                    candidate = self.tokenizer.decode(token_ids[:count], skip_special_tokens=True)
                except TypeError:
                    candidate = self.tokenizer.decode(token_ids[:count])
                if candidate:
                    return candidate
        except (AttributeError, TypeError, ValueError):
            pass
        return text[:budget]

    def _truncate_with_encoding(self, text: str, budget: int, encoding: Any) -> str:
        try:
            token_ids = encoding.encode(text)
            return encoding.decode(token_ids[:budget])
        except Exception:
            return text[:budget]

    def _token_count(self, text: str) -> int:
        if self.tokenizer is not None:
            try:
                return len(self.tokenizer.encode(text, add_special_tokens=False))
            except (AttributeError, TypeError, ValueError):
                pass
        encoding = self._get_tiktoken_encoding()
        if encoding is not None:
            try:
                return len(encoding.encode(text))
            except Exception:
                return len(text)
        return len(text)

    def _shrink(self, text: str, budget: int) -> str:
        if self.tokenizer is not None:
            return self._truncate_with_tokenizer(text, budget)
        encoding = self._get_tiktoken_encoding()
        if encoding is not None:
            return self._truncate_with_encoding(text, budget, encoding)
        return text[:budget]

    def _embed_with_context_retry(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._embed(texts)
        except Exception as exc:
            if not _is_context_overflow(exc):
                raise
            if len(texts) == 1:
                return self._retry_overflowing_item(texts[0])
            vectors: list[list[float]] = []
            for text in texts:
                vectors.extend(self._embed_with_context_retry([text]))
            return vectors

    def _retry_overflowing_item(self, text: str) -> list[list[float]]:
        current = text
        budget = self.max_input_chars if self.max_input_chars and self.max_input_chars > 0 else self._token_count(text)
        for attempt in range(1, 4):
            budget = max(budget // 2, 1)
            shortened = self._shrink(current, budget)
            if len(shortened) >= len(current):
                shortened = current[: max(len(current) // 2, 0)]
            current = shortened
            logger.warning(
                "Embedding input exceeded context; retrying item with budget %d (attempt %d/3).",
                budget,
                attempt,
            )
            try:
                return self._embed([current])
            except Exception as exc:
                if not _is_context_overflow(exc) or attempt == 3:
                    raise
        raise RuntimeError("Embedding context retry failed.")

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


def _is_context_overflow(exc: Exception) -> bool:
    message = str(exc).lower()
    code = str(getattr(exc, "code", "")).lower()
    explicit_codes = ("context_length_exceeded", "input_too_long", "max_tokens_exceeded")
    if any(marker in code for marker in explicit_codes):
        return True
    if "http 400" not in message and not any(marker in message for marker in explicit_codes):
        return False
    return any(
        marker in message
        for marker in (
            "context length",
            "maximum context",
            "context window",
            "input too long",
            "too many tokens",
            "sequence length",
            "max_seq_len",
            "context_length_exceeded",
            "input_too_long",
            "max_tokens_exceeded",
        )
    )
