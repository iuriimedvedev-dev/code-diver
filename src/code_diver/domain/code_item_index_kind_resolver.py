from __future__ import annotations

from .code_item import CodeItem
from .code_item_index_kind import CodeItemIndexKind
from .code_item_metadata import CodeItemMetadata


class CodeItemIndexKindResolver:
    def resolve(self, item: CodeItem) -> str:
        explicit = item.metadata.get(CodeItemMetadata.INDEX_KIND)
        if explicit:
            return str(explicit)
        if item.metadata.get(CodeItemMetadata.SYMBOL):
            return CodeItemIndexKind.SYMBOL
        if item.metadata.get(CodeItemMetadata.SOURCE):
            return CodeItemIndexKind.CHUNK
        return CodeItemIndexKind.UNKNOWN
