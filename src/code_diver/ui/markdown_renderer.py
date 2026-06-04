from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown

from ..config.ui_config import UiConfig
from ..settings import Defaults


class MarkdownRenderer:
    def __init__(self, config: UiConfig):
        self.config = config
        self.console = Console(color_system="auto" if config.color else None)

    def render(self, text: str) -> None:
        markdown = Markdown(text)
        pager = self.config.pager.lower()
        if pager == "always" or (pager == Defaults.UI_PAGER and len(text.splitlines()) > 40):
            with self.console.pager(styles=True):
                self.console.print(markdown)
            return
        self.console.print(markdown)
