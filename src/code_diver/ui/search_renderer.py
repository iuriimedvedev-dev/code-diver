from __future__ import annotations

from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..config.ui_config import UiConfig
from ..domain import SearchResult
from ..settings import Defaults
from .file_link_builder import FileLinkBuilder
from .language_detector import LanguageDetector
from .search_snippet_builder import SearchSnippetBuilder


class SearchRenderer:
    def __init__(self, root: Path, config: UiConfig, preview_lines: int):
        self.root = root
        self.config = config
        self.preview_lines = preview_lines
        self.console = Console(color_system="auto" if config.color else None)
        self.snippets = SearchSnippetBuilder()
        self.languages = LanguageDetector()
        self.links = FileLinkBuilder()

    def render(self, query: str, results: list[SearchResult]) -> None:
        renderable = Group(*self._result_panels(query, results))
        pager = self.config.pager.lower()
        should_page = pager == "always" or (pager == Defaults.UI_PAGER and len(results) > 3)
        if should_page:
            with self.console.pager(styles=True):
                self.console.print(renderable)
        else:
            self.console.print(renderable)

    def _result_panels(self, query: str, results: list[SearchResult]) -> list[Panel]:
        panels: list[Panel] = []
        for rank, result in enumerate(results, start=1):
            item = result.item
            snippet = self.snippets.build(item, query, self.preview_lines)
            title = self.links.build(self.root, item.path, snippet.start_line, self.config.links)
            table = Table.grid(expand=True)
            table.add_column(ratio=1)
            table.add_row(
                Text.from_markup(
                    f"[bold cyan]#{rank}[/bold cyan] {title}  "
                    f"[dim]score={result.score:.4f} lines={snippet.start_line}-{snippet.end_line}[/dim]"
                )
            )
            syntax = Syntax(
                snippet.text,
                self.languages.detect(item.path),
                line_numbers=True,
                start_line=snippet.start_line,
                word_wrap=False,
                theme="ansi_dark",
            )
            table.add_row(syntax)
            panels.append(Panel(table, border_style="bright_black", padding=(0, 1)))
        return panels
