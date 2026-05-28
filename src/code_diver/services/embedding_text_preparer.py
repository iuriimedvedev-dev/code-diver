from __future__ import annotations

from ..domain import CodeItem


class EmbeddingTextPreparer:
    def __init__(self, max_input_chars: int | None = None):
        self.max_input_chars = max_input_chars

    def prepare(self, item: CodeItem) -> str:
        text = item.to_embedding_text()
        if self.max_input_chars is None or self.max_input_chars <= 0:
            return text
        return text[: self.max_input_chars]
