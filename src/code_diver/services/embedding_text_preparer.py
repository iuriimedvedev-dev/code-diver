from __future__ import annotations

from typing import Any

from ..domain import CodeItem


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
    """Keep the configured character contract while avoiding partial tokens when possible."""
    if len(text) <= max_input_chars:
        return text
    if tokenizer is None:
        return text[:max_input_chars]
    try:
        token_ids = tokenizer.encode(text, add_special_tokens=False)
        for count in range(len(token_ids), 0, -1):
            try:
                candidate = tokenizer.decode(token_ids[:count], skip_special_tokens=True)
            except TypeError:
                candidate = tokenizer.decode(token_ids[:count])
            if len(candidate) <= max_input_chars:
                return candidate
    except (AttributeError, TypeError, ValueError):
        pass
    return text[:max_input_chars]
