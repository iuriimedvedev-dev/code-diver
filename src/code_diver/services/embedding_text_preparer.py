from __future__ import annotations

from typing import Any

from ..domain import CodeItem
from ..settings import Defaults

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None


class EmbeddingTextPreparer:
    def __init__(
        self,
        max_input_chars: int | None = None,
        tokenizer: Any | None = None,
        max_input_tokens: int = Defaults.EMBEDDING_MAX_INPUT_TOKENS,
        token_safety_margin: int = Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN,
    ):
        self.max_input_chars = max_input_chars
        self.tokenizer = tokenizer
        self.max_input_tokens = max_input_tokens
        self.token_safety_margin = token_safety_margin

    def prepare(self, item: CodeItem) -> str:
        text = item.to_embedding_text()
        if self.max_input_chars is None or self.max_input_chars <= 0:
            return text
        return truncate_embedding_text(
            text,
            self.max_input_chars,
            self.tokenizer,
            max_input_tokens=self.max_input_tokens,
            token_safety_margin=self.token_safety_margin,
        )


_MODEL_MAX_TOKENS = Defaults.EMBEDDING_MAX_INPUT_TOKENS
# Leave headroom for special tokens and Qwen vs tiktoken mismatch.
_TOKEN_SAFETY_MARGIN = Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN


def truncate_embedding_text(
    text: str,
    max_input_chars: int,
    tokenizer: Any | None = None,
    max_input_tokens: int = Defaults.EMBEDDING_MAX_INPUT_TOKENS,
    token_safety_margin: int = Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN,
) -> str:
    """Use token-aware truncation when available, with a character fallback.

    `max_input_chars` is the maximum CHARACTER count of the summary text
    (the text to send to the embedding model). The model's actual token
    limit (`_MODEL_MAX_TOKENS`, default 512) is used for token-level
    truncation so the embedding server never rejects the input.

    When tokenizer is available, the text is truncated to the safe token budget,
    then further limited to `max_input_chars` chars if needed.
    """
    max_tokens = max(1, int(max_input_tokens) - int(token_safety_margin))
    try:
        if tokenizer is not None:
            token_ids = tokenizer.encode(text, add_special_tokens=False)
            count = min(len(token_ids), max_tokens)
            if count >= len(token_ids):
                result = text
            else:
                result = None
                for c in range(count, 0, -1):
                    try:
                        candidate = tokenizer.decode(token_ids[:c], skip_special_tokens=True)
                    except TypeError:
                        candidate = tokenizer.decode(token_ids[:c])
                    if candidate:
                        result = candidate
                        break
                if result is None:
                    result = text[:max_input_chars]
        else:
            if tiktoken is None:
                raise ImportError("tiktoken is unavailable")
            encoding = tiktoken.get_encoding("cl100k_base")
            token_ids = encoding.encode(text)
            if len(token_ids) <= max_tokens:
                result = text
            else:
                result = encoding.decode(token_ids[:max_tokens])
        if len(result) > max_input_chars:
            return result[:max_input_chars]
        return result
    except Exception:
        return text[: min(max_input_chars, max_tokens * 3)]


def shrink_embedding_text(
    text: str,
    tokenizer: Any | None = None,
    max_input_tokens: int = Defaults.EMBEDDING_MAX_INPUT_TOKENS,
    token_safety_margin: int = Defaults.EMBEDDING_TOKEN_SAFETY_MARGIN,
) -> str:
    """Reduce an overflowing input without cutting through a decoded token when possible."""
    if not text:
        return text
    if len(text) == 1:
        return ""
    return truncate_embedding_text(
        text,
        max(len(text) // 2, 1),
        tokenizer,
        max_input_tokens=max_input_tokens,
        token_safety_margin=token_safety_margin,
    )
