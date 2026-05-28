from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SearchSnippet:
    text: str
    start_line: int
    end_line: int
