"""Command parser and CLI dispatcher for Code Diver."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..config import AppConfig
from ..inspection.info_service import InfoService
from ..runtime.embedding_runtime_manager import EmbeddingProfileRegistry
from ..settings.cli_names import ADVANCED_COMMANDS, CommandName, OptionName
from .answering import (
    cmd_answer,
    cmd_answer_pairwise,
    cmd_answer_report,
    cmd_answer_report_judge,
    cmd_ask,
    cmd_chat,
)
from .indexing import (
    cmd_index,
    cmd_index_clear,
    cmd_index_selected,
)
from .inspection import (
    cmd_grep,
    cmd_info,
    cmd_open,
    cmd_read,
    cmd_rg,
    cmd_symbols,
    cmd_tree,
)
from .search import (
    cmd_search,
)


def status_console() -> Console:
    return Console(stderr=True, color_system="auto")


def render_status_panel(
    title: str, rows: list[tuple[str, object]], border_style: str = "cyan"
) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    for key, value in rows:
        table.add_row(key, str(value))
    status_console().print(
        Panel(
            table,
            title=f"[bold]{title}[/bold]",
            border_style=border_style,
            expand=False,
        )
    )
