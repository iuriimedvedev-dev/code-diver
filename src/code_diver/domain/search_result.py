from __future__ import annotations

from dataclasses import dataclass

from .code_item import CodeItem


@dataclass(slots=True)
class SearchResult:
    item: CodeItem
    score: float
