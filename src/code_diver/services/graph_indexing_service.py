from __future__ import annotations

from pathlib import Path

from ..domain import CodeItem
from ..graph import CodeGraphBuilder, CodeGraphStore


class GraphIndexingService:
    def __init__(self, builder: CodeGraphBuilder, store: CodeGraphStore):
        self.builder = builder
        self.store = store

    def build(self, root: Path, items: list[CodeItem]) -> None:
        self.store.save(self.builder.build(root, items))
