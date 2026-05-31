from __future__ import annotations

from ..domain import CodeItem
from ..services.tokenizer import tokenize
from ..settings import SchemaKey
from .hybrid_item_profile import HybridItemProfile


class HybridItemProfiler:
    def profile(self, item: CodeItem) -> HybridItemProfile:
        return HybridItemProfile(
            title_terms=frozenset(tokenize(item.title)),
            path_terms=frozenset(tokenize(item.path)),
            content_terms=frozenset(tokenize(item.content)),
            metadata_terms=frozenset(self._metadata_terms(item)),
        )

    def _metadata_terms(self, item: CodeItem) -> set[str]:
        values: list[str] = []
        for key in (SchemaKey.KIND.value, SchemaKey.SYMBOL.value, SchemaKey.SOURCE.value):
            value = item.metadata.get(key)
            if value:
                values.append(str(value))
        return {token for value in values for token in tokenize(value)}
