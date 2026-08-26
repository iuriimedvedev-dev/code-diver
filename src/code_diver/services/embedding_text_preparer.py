from __future__ import annotations

from typing import Any

from ..domain import CodeItem

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None


class EmbeddingTextPreparer:
    def __init__(self, max_input_chars: int | None = None, tokenizer: Any | None = None):
        self.max_input_chars = max_input_chars
        self.tokenizer = tokenizer

    def prepare(self, item: CodeItem) -> str:
        text = item.to_embedding_text()
        if self.max_input_chars is None or self.max_input_chars <= 0:
            return text
        return truncate_embedding_text(text, self.max_input_chars, self.tokenizer)


def truncate_embedding_text(text: str, max_input_chars: int, tokenizer: Any | None = None) -> str:
    """Use token-aware truncation when available, with a character fallback."""
    if len(text) <= max_input_chars:
        return text
    try:
        if tokenizer is not None:
            token_ids = tokenizer.encode(text, add_special_tokens=False)
            for count in range(min(len(token_ids), max_input_chars), 0, -1):
                try:
                    candidate = tokenizer.decode(token_ids[:count], skip_special_tokens=True)
                except TypeError:
                    candidate = tokenizer.decode(token_ids[:count])
                if candidate:
                    return candidate
        else:
            if tiktoken is None:
                raise ImportError("tiktoken is unavailable")
            encoding = tiktoken.get_encoding("cl100k_base")
            token_ids = encoding.encode(text)
            if len(token_ids) <= max_input_chars:
                return text
            return encoding.decode(token_ids[:max_input_chars])
    except Exception:
        return text[: max_input_chars // 3]
    return text[: max_input_chars // 3]


def shrink_embedding_text(text: str, tokenizer: Any | None = None) -> str:
    """Reduce an overflowing input without cutting through a decoded token when possible."""
    if not text:
        return text
    if len(text) == 1:
        return ""
    return truncate_embedding_text(text, max(len(text) // 2, 1), tokenizer)
