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

try:
    from openai import BadRequestError
except ImportError:  # pragma: no cover - optional dependency
    class BadRequestError(Exception):
        pass

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
        max_input_tokens: int = Defaults.EMBEDDING_MAX_INPUT_TOKENS,
        token_safety_margin: int = Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN,
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
        self.max_input_tokens = max(1, int(max_input_tokens))
        self.token_safety_margin = max(0, int(token_safety_margin))
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

    # Class-level fallbacks for subclasses/tests that bypass __init__. The effective values are
    # the instance attributes fed from `embedding.max_input_tokens` / `embedding.token_safety_margin`.
    # Keep margin for special tokens + tokenizer mismatch between the local Qwen count and the
    # server (rejects observed at 513 with margin=2).
    _MODEL_MAX_TOKENS = Defaults.EMBEDDING_MAX_INPUT_TOKENS
    _TOKEN_SAFETY_MARGIN = Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN

    def _bounded_prefixed(self, prefix: str | None, text: str, limit: int | None = None) -> str:
        """Cap by chars then by tokens. Never trust char/token ratio heuristics.

        H-70: with max_input_chars raised toward the real window (~2000), the old
        early-exit `len <= max_tokens * 5` skipped token truncation and let 513+
        token payloads reach the server. Always enforce the token budget.
        """
        prefixed = self._prefixed(prefix, text)
        max_input_chars = self.max_input_chars if limit is None else limit
        if max_input_chars is None or max_input_chars <= 0:
            # Still enforce the model token window when no char cap is configured.
            max_input_chars = 10**9
        if len(prefixed) > max_input_chars:
            prefixed = prefixed[:max_input_chars]
        token_budget = self._effective_token_budget()
        # Optional `limit` callers (context-retry) pass a tighter token-ish budget.
        if limit is not None and limit < token_budget:
            token_budget = max(1, limit)
        try:
            self._ensure_tokenizer()
            if self.tokenizer is not None:
                truncated = self._truncate_with_tokenizer(prefixed, token_budget)
            else:
                if tiktoken is None:
                    raise ImportError("tiktoken is unavailable")
                try:
                    encoding = tiktoken.encoding_for_model(self.model)
                except Exception:
                    encoding = tiktoken.get_encoding("cl100k_base")
                token_ids = encoding.encode(prefixed)
                if len(token_ids) <= token_budget:
                    truncated = prefixed
                else:
                    truncated = encoding.decode(token_ids[:token_budget])
            if len(truncated) > max_input_chars:
                return truncated[:max_input_chars]
            return truncated
        except Exception:
            # Conservative char fallback: ~2.5 chars/token undercounts code density less
            # badly than the previous *5 heuristic that skipped truncation entirely.
            char_cap = min(max_input_chars, token_budget * 3)
            return prefixed[:char_cap]

    def _effective_token_budget(self) -> int:
        max_tokens = getattr(self, "max_input_tokens", self._MODEL_MAX_TOKENS)
        margin = getattr(self, "token_safety_margin", self._TOKEN_SAFETY_MARGIN)
        return max(1, int(max_tokens) - int(margin))

    def _ensure_tokenizer(self) -> None:
        """Lazily bind a real model tokenizer for Qwen/local embeds when available."""
        if self.tokenizer is not None or getattr(self, "_tokenizer_load_attempted", False):
            return
        self._tokenizer_load_attempted = True
        model = (self.model or "").lower()
        if "qwen" not in model and "embedding" not in model:
            return
        try:
            from transformers import AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(self.model, trust_remote_code=True)
        except Exception:
            # Leave tokenizer as None; tiktoken/char fallback still applies.
            self.tokenizer = None

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
            # Catch broad Exception: openai.BadRequestError needs an httpx response we
            # do not have from urllib, so context-length 400s are raised as RuntimeError.
            if not _is_context_length_bad_request(exc):
                raise
            if len(texts) == 1:
                return self._retry_overflowing_item(texts[0])
            vectors: list[list[float]] = []
            for text in texts:
                vectors.extend(self._embed_with_context_retry([text]))
            return vectors

    def _retry_overflowing_item(self, text: str) -> list[list[float]]:
        current = text
        budget = self.max_input_chars if self.max_input_chars and self.max_input_chars > 0 else len(text)
        for attempt in range(2, 4):
            budget = max(budget // 2, 1)
            max_tokens = min(getattr(self, "max_input_tokens", self._MODEL_MAX_TOKENS), budget)
            shortened = self._bounded_prefixed(None, current, max_tokens)
            if len(shortened) >= len(current):
                shortened = current[: max(len(current) // 2, 1)]
            current = shortened
            logger.warning(
                "Embedding input exceeded context; retrying item with budget %d (attempt %d/3).",
                max_tokens,
                attempt,
            )
            try:
                return self._embed([current])
            except Exception as exc:
                if not _is_context_length_bad_request(exc) or attempt == 3:
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
            # Always RuntimeError: openai.BadRequestError requires httpx response/body
            # kwargs that urllib cannot supply (raises APIStatusError init TypeError and
            # previously masked the real context-length payload).
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


def _is_context_length_bad_request(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "maximum context length",
            "context length",
            "input_tokens",
            "please reduce the length of the input",
        )
    )
