from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.table import Table

from ..config import AppConfig
from ..inspection import (
    CodebaseInfo,
    GrepService,
    InfoService,
    ReadExcerptService,
    RgService,
    SymbolsService,
    TreeService,
)
from ..inspection.exclude_patterns import inspection_exclude_patterns
from ..ui import EditorOpener


def normalize_query(query: str | list[str]) -> str:
    """Normalize query strings or list of tokens into a single trimmed string."""
    if isinstance(query, list):
        return " ".join(query).strip()
    return query.strip()


def format_open_location(path: str, start_line: int | None = None) -> str:
    """Format file path and optional start line for open command reporting."""
    if start_line is not None:
        return f"{path}:{start_line}"
    return path


def print_inspection_error(error: Exception | str, file: Any = None) -> int:
    """Print an inspection error message to stderr and return failure exit code (1)."""
    target = file if file is not None else sys.stderr
    print(f"error: {error}", file=target)
    return 1


def render_info_metrics(info: CodebaseInfo) -> Table:
    """Build a rich Table showing the Code Diver Index & Storage Overview metrics."""
    table = Table(
        title="[bold cyan]Code Diver Index & Storage Overview[/bold cyan]",
        show_header=True,
    )
    table.add_column("Category", style="bold yellow")
    table.add_column("Property", style="bold")
    table.add_column("Value", style="green")

    # Root
    table.add_row("Codebase", "Root Directory", info.root)

    # Vector Store
    table.add_row("Vector Store", "Provider", info.store.provider)
    table.add_row("Vector Store", "Indexed Items / Chunks", f"{info.store.items_count:,}")
    if info.store.location:
        table.add_row("Vector Store", "Location / Endpoint", str(info.store.location))
    if info.store.disk_size_human:
        table.add_row("Vector Store", "Disk Footprint", info.store.disk_size_human)
    for k, v in info.store.metadata.items():
        if v:
            table.add_row("Vector Store", f"Metadata: {k}", str(v))

    # Graph Store
    table.add_row("Graph Index", "Enabled", str(info.graph.enabled))
    table.add_row("Graph Index", "Artifact Exists", str(info.graph.exists))
    table.add_row("Graph Index", "Artifact Path", info.graph.path)
    if info.graph.exists:
        table.add_row("Graph Index", "Disk Footprint", info.graph.disk_size_human)

    # .code-diver directory
    table.add_row("Artifacts", ".code-diver Dir", info.code_diver_dir.path)
    if info.code_diver_dir.exists:
        table.add_row("Artifacts", ".code-diver Total Size", info.code_diver_dir.disk_size_human)

    # Models
    table.add_row(
        "Embedding",
        "Provider & Model",
        f"{info.embedding['provider']} ({info.embedding['model']})",
    )
    table.add_row(
        "Embedding",
        "Dimensions & Batch",
        f"{info.embedding['dimensions']}d / batch {info.embedding['batch_size']}",
    )
    table.add_row(
        "Generation",
        "Provider & Model",
        f"{info.generation['provider']} ({info.generation['model']})",
    )

    return table


def cmd_tree(args: argparse.Namespace, config: AppConfig) -> int:
    """Print a gitignore-aware repository tree."""
    print(
        TreeService(config.root, inspection_exclude_patterns(config)).render(
            path=args.path, max_depth=args.depth, limit=args.limit
        )
    )
    return 0


def cmd_grep(args: argparse.Namespace, config: AppConfig) -> int:
    """Perform literal gitignore-aware text search."""
    print(
        GrepService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(args.pattern, path=args.path, limit=args.limit)
    )
    return 0


def cmd_rg(args: argparse.Namespace, config: AppConfig) -> int:
    """Perform regex gitignore-aware text search via rg."""
    print(
        RgService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).search(args.pattern, path=args.path, limit=args.limit)
    )
    return 0


def cmd_read(args: argparse.Namespace, config: AppConfig) -> int:
    """Read a bounded, gitignore-aware file excerpt."""
    print(
        ReadExcerptService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(args.file, start_line=args.start_line, lines=args.lines)
    )
    return 0


def cmd_symbols(args: argparse.Namespace, config: AppConfig) -> int:
    """List parsed source symbols for a repository or specific path."""
    print(
        SymbolsService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(path=args.path, limit=args.limit)
    )
    return 0


def cmd_info(args: argparse.Namespace, config: AppConfig) -> int:
    """Display index metadata and storage metrics."""
    service = InfoService(config)
    info = service.get_info()
    if bool(getattr(args, "json", False)):
        print(json.dumps(info.to_dict(), indent=2))
        return 0

    console = Console()
    table = render_info_metrics(info)
    console.print(table)
    return 0


def cmd_open(
    args: argparse.Namespace,
    config: AppConfig,
    search_fn: Callable[[AppConfig, str, int], list[Any]] | None = None,
) -> int:
    """Open the best search result in the configured editor."""
    rank = max(int(args.rank), 1)
    limit = max(rank, config.search.limit)
    if search_fn is None:
        from ..cli import run_search

        search_fn = run_search
    results = search_fn(config, normalize_query(args.query), limit)
    if not results:
        print("No search results.")
        return 1
    if rank > len(results):
        print(f"Only {len(results)} search results available.")
        return 1
    result = results[rank - 1]
    command_line = EditorOpener(config.root, config.ui).open(result)
    location = format_open_location(result.item.path, result.item.start_line)
    print(f"Opened {location} with: {' '.join(command_line)}")
    return 0


__all__ = [
    "cmd_grep",
    "cmd_info",
    "cmd_open",
    "cmd_read",
    "cmd_rg",
    "cmd_symbols",
    "cmd_tree",
    "format_open_location",
    "normalize_query",
    "print_inspection_error",
    "render_info_metrics",
]
