from __future__ import annotations

from ..domain import CodeItem
from ..services.tokenizer import tokenize
from .search_snippet import SearchSnippet


class SearchSnippetBuilder:
    def build(self, item: CodeItem, query: str, preview_lines: int) -> SearchSnippet:
        lines = item.content.splitlines()
        if not lines:
            start = item.start_line or 1
            return SearchSnippet("", start, start)

        query_tokens = set(tokenize(query))
        best_index = self._best_line_index(lines, query_tokens)
        window = max(preview_lines, 1)
        half_window = window // 2
        start_index = max(best_index - half_window, 0)
        end_index = min(start_index + window, len(lines))
        start_index = max(end_index - window, 0)

        absolute_start = (item.start_line or 1) + start_index
        absolute_end = (item.start_line or 1) + end_index - 1
        return SearchSnippet("\n".join(lines[start_index:end_index]), absolute_start, absolute_end)

    def _best_line_index(self, lines: list[str], query_tokens: set[str]) -> int:
        if not query_tokens:
            return 0
        best_index = 0
        best_score = -1
        for index, line in enumerate(lines):
            line_tokens = set(tokenize(line))
            score = len(query_tokens & line_tokens)
            if score > best_score:
                best_score = score
                best_index = index
        return best_index
