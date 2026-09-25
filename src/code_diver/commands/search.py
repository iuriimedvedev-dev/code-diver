from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..config import AppConfig
from ..domain import SearchResult
from ..pi import AgyCliAgentRunner, GeminiCliAgentRunner, PiRunner
from ..plugins import PluginManager
from ..providers.embedding_provider_builder import make_embedding_provider
from ..runtime.qdrant_runtime_manager import QdrantRuntimeManager
from ..settings import Defaults, SchemaKey, VectorStoreProviderId
from ..store.vector_store_factory import create_vector_store
from ..strategies.retrieval_strategy_builder import make_retrieval_strategy
from ..ui import MarkdownRenderer, SearchRenderer


def normalize_query(query: str | list[str] | None) -> str:
    """Normalize query strings or list of tokens into a single trimmed string."""
    if query is None:
        return ""
    if isinstance(query, list):
        return " ".join(query).strip()
    return query.strip()


def result_to_json(result: SearchResult) -> dict[str, Any]:
    """Serialize a single SearchResult into a dictionary containing score and item."""
    return {
        SchemaKey.SCORE.value: result.score,
        SchemaKey.ITEM.value: result.item.to_json(),
    }


def format_search_result(result: SearchResult) -> dict[str, Any]:
    """Alias for result_to_json."""
    return result_to_json(result)


def search_output_formatter(
    results: list[SearchResult] | SearchResult,
    as_json: bool = False,
    indent: int = 2,
) -> list[dict[str, Any]] | dict[str, Any] | str:
    """Format search results into structured JSON-compatible dictionaries or a JSON string."""
    if isinstance(results, list):
        formatted: list[dict[str, Any]] | dict[str, Any] = [
            result_to_json(result) for result in results
        ]
    else:
        formatted = result_to_json(results)
    if as_json:
        return json.dumps(formatted, indent=indent)
    return formatted


def sort_results_by_score(
    results: list[SearchResult], reverse: bool = True
) -> list[SearchResult]:
    """Sort search results by score descending."""
    return sorted(results, key=lambda r: r.score, reverse=reverse)


def status_console() -> Console:
    """Return the console instance used for status messages and progress reporting."""
    return Console(stderr=True, color_system="auto")


def render_status_panel(
    title: str, rows: list[tuple[str, object]], border_style: str = "cyan"
) -> None:
    """Render a structured status panel to stderr."""
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
            padding=(0, 1),
        )
    )


def render_status_line(message: str, style: str = "cyan") -> None:
    """Render a single status line prefixed with [code-diver]."""
    status_console().print(f"[{style}]\\[code-diver][/{style}] {message}")


@contextlib.contextmanager
def render_activity(message: str, enabled: bool = True, style: str = "cyan"):
    """Context manager to display an active spinner and message."""
    if not enabled:
        yield
        return
    progress = Progress(
        TextColumn(f"[{style}]\\[code-diver][/{style}] {message}"),
        SpinnerColumn("dots"),
        console=status_console(),
        transient=True,
    )
    with progress:
        yield


def store_label(config: AppConfig) -> str:
    """Format a human-readable identifier for the configured vector store."""
    provider = config.storage.provider
    if provider == VectorStoreProviderId.QDRANT.value:
        return f"{provider}:{config.storage.qdrant.collection}"
    return str(config.artifact)


def close_vector_store(vector_store: Any) -> None:
    """Close the vector store connection if applicable."""
    close = getattr(vector_store, "close", None)
    if callable(close):
        close()


def ensure_storage_runtime(config: AppConfig, progress: bool = True) -> None:
    """Ensure supporting runtime dependencies (e.g. Qdrant) are ready."""
    manager = QdrantRuntimeManager(config)
    if not manager.should_manage():
        return
    with render_activity(
        f"checking local Qdrant from config: {config.storage.qdrant.url}",
        enabled=progress,
        style="blue",
    ):
        status = manager.ensure_running()
    if progress and status.started:
        render_status_line(
            f"started local Qdrant: {config.storage.qdrant.url}", "green"
        )


def make_vector_store(config: AppConfig, progress: bool = False):
    """Create and return a vector store instance for the given configuration."""
    ensure_storage_runtime(config, progress=progress)
    return create_vector_store(config)


def make_plugin_manager(config: AppConfig) -> PluginManager:
    """Instantiate a PluginManager from configured plugin paths."""
    return PluginManager([Path(path) for path in config.plugins])


def run_search(config: AppConfig, query: str, limit: int) -> list[SearchResult]:
    """Execute search retrieval for the given query up to limit."""
    vector_store = make_vector_store(config)
    try:
        if not vector_store.exists():
            raise ValueError(
                f"Index not found in {store_label(config)}. Run `code-diver index` first."
            )
        provider = make_embedding_provider(config, vector_store.metadata())
        prepared_query = make_plugin_manager(config).prepare_query(query)
        return make_retrieval_strategy(config, provider, vector_store).search(
            prepared_query, limit
        )
    finally:
        close_vector_store(vector_store)


def search_agent_binary_available(config: AppConfig) -> bool:
    """Check if the configured search agent binary is available on PATH or disk."""
    binary = search_agent_binary(config)
    return bool(shutil.which(binary) or Path(binary).exists())


def search_agent_binary(config: AppConfig) -> str:
    """Resolve the executable binary name/path for the search agent."""
    if (
        config.pi.provider in GeminiCliAgentRunner.PROVIDERS
        and config.pi.binary == Defaults.PI_BINARY
    ):
        return Defaults.GEMINI_CLI_BINARY
    if (
        config.pi.provider in AgyCliAgentRunner.PROVIDERS
        and config.pi.binary == Defaults.PI_BINARY
    ):
        return Defaults.AGY_CLI_BINARY
    return config.pi.binary


def make_search_agent_runner(config: AppConfig):
    """Instantiate the appropriate agent runner based on the configured provider."""
    if config.pi.provider in AgyCliAgentRunner.PROVIDERS:
        return AgyCliAgentRunner()
    if config.pi.provider in GeminiCliAgentRunner.PROVIDERS:
        return GeminiCliAgentRunner()
    return PiRunner()


def build_code_exploration_prompt(query: str) -> str:
    """Generate the structured exploration system/user prompt for the search agent."""
    return f"""You are Code Diver's code exploration agent.

Answer the user's repository question by using the registered read-only code_diver tools.

User question:
{query}

Required workflow:
1. Start with code_diver_search or code_diver_inspect. Run multiple independent search probes in parallel when useful.
2. Convert the user's wording into several search intents: exact identifiers, likely file/path names, domain concepts, and implementation responsibilities.
3. Verify the top candidates with symbols, grep/rg, and bounded reads before making claims.
4. Explain the code, not only where it is. Cover the owner file/function/class, how control or data flows through it, and why the cited locations answer the question.
5. Cite every important claim with relative file paths and line numbers from tool output.
6. If evidence is weak, say what was checked and what remains uncertain.

Output format:
- Short answer first.
- Evidence table with file/function/lines/relevance.
- Explanation of the mechanism.
- Optional follow-up probes only if they are genuinely useful.

Do not edit files. Do not invent APIs, symbols, or line numbers."""


def search_agent_prompt(config: AppConfig, query: str) -> str:
    """Build the prompt string for the search agent runner."""
    if (
        config.pi.provider in AgyCliAgentRunner.PROVIDERS
        or config.pi.provider in GeminiCliAgentRunner.PROVIDERS
    ):
        return query
    return build_code_exploration_prompt(query)


def run_deterministic_search_fallback(
    config: AppConfig, query: str, limit: int, missing_binary: str
) -> int:
    """Run search directly and render results without agent when agent binary is missing."""
    render_status_panel(
        "Deterministic Search Fallback",
        [
            ("reason", f"Search agent binary is not available: {missing_binary}"),
            ("mode", "retrieval only; no LLM explanation"),
            ("json", f'uv run code-diver --root {config.root} search "{query}" --json'),
        ],
        border_style="yellow",
    )
    with render_activity(
        "running deterministic retrieval over the existing index",
        enabled=True,
        style="yellow",
    ):
        results = run_search(config, query, limit)
    SearchRenderer(config.root, config.ui, config.search.preview_lines).render(
        query, results
    )
    return 0


def code_explorer_preflight(config: AppConfig, config_path: Path | None) -> bool:
    """Pre-flight check before launching the search agent."""
    if config.pi.provider in AgyCliAgentRunner.PROVIDERS:
        render_status_panel(
            "Search Agent",
            [
                ("root", str(config.root.resolve())),
                ("config", str((config_path or Defaults.CONFIG_PATH).resolve())),
                ("backend", "Antigravity CLI"),
                ("mode", "read-only sandbox"),
                ("model", config.pi.model or "default"),
            ],
            border_style="cyan",
        )
        return True
    if config.pi.provider in GeminiCliAgentRunner.PROVIDERS:
        render_status_panel(
            "Search Agent",
            [
                ("root", str(config.root.resolve())),
                ("config", str((config_path or Defaults.CONFIG_PATH).resolve())),
                ("backend", "Gemini CLI"),
                ("mode", "read-only plan"),
                ("model", config.pi.model or "default"),
            ],
            border_style="cyan",
        )
        return True
    render_status_panel(
        "Search Agent",
        [
            ("root", config.root.resolve()),
            ("config", (config_path or Defaults.CONFIG_PATH).resolve()),
            ("store", store_label(config)),
            ("model", config.pi.model or "default"),
            (
                "tools",
                ", ".join(config.pi.tools) if config.pi.tools else "(none configured)",
            ),
        ],
    )
    vector_store = make_vector_store(config)
    try:
        if not vector_store.exists():
            render_status_panel(
                "Index Missing",
                [
                    ("store", store_label(config)),
                    ("fix", f"uv run code-diver --root {config.root} index"),
                    (
                        "raw check",
                        f'uv run code-diver --root {config.root} search "your query" --json',
                    ),
                ],
                border_style="red",
            )
            return False
        metadata = vector_store.metadata()
        count_items = getattr(vector_store, "count_items", None)
        item_count = count_items() if callable(count_items) else None
        model = metadata.get(SchemaKey.MODEL.value) or "unknown"
        provider = metadata.get(SchemaKey.PROVIDER.value) or "unknown"
        dimensions = metadata.get(SchemaKey.DIMENSIONS.value) or "unknown"
        rows: list[tuple[str, object]] = [
            ("provider", provider),
            ("model", model),
            ("dimensions", dimensions),
        ]
        if item_count is not None:
            rows.append(("items", item_count))
        render_status_panel("Index Ready", rows, border_style="green")
        render_status_line(
            "starting agent: search, verify, read bounded excerpts, explain",
            "green",
        )
        return True
    except Exception as exc:
        render_status_panel(
            "Index Error",
            [
                ("store", store_label(config)),
                ("cause", exc),
                ("qdrant", "docker compose up -d qdrant"),
            ],
            border_style="red",
        )
        return False
    finally:
        close_vector_store(vector_store)


def cmd_search(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute the search command either via JSON, agent, or deterministic fallback."""
    query = normalize_query(getattr(args, "query", None))
    interactive = bool(getattr(args, "interactive", False))
    as_json = bool(getattr(args, "json", False))

    if not query and not interactive:
        print(
            "error: search query is required unless -i/--interactive is used.",
            file=sys.stderr,
        )
        return 1
    if as_json:
        limit = getattr(args, "limit", None) or config.search.limit
        results = run_search(config, query, limit)
        print(json.dumps(search_output_formatter(results), indent=2))
        return 0
    if not as_json and not code_explorer_preflight(config, getattr(args, "config", None)):
        return 1
    if not search_agent_binary_available(config):
        if interactive:
            render_status_panel(
                "Search Agent Unavailable",
                [
                    ("binary", config.pi.binary),
                    (
                        "fix",
                        "install/configure the Search agent runtime, or use non-interactive search",
                    ),
                    (
                        "deterministic",
                        f'uv run code-diver --root {config.root} search "{query}" --json',
                    ),
                ],
                border_style="red",
            )
            return 1
        limit = getattr(args, "limit", None) or config.search.limit
        return run_deterministic_search_fallback(
            config, query, limit, config.pi.binary
        )
    if interactive:
        prompt = search_agent_prompt(config, query) if query else None
        return make_search_agent_runner(config).run_interactive(
            config, getattr(args, "config", None), prompt=prompt
        )
    with render_activity(
        "running Search agent: planning tool calls, reading bounded excerpts, preparing answer",
        enabled=True,
        style="green",
    ):
        exit_code, output = make_search_agent_runner(config).run_print_capture(
            config,
            getattr(args, "config", None),
            search_agent_prompt(config, query),
            toolset=None,
            hypothesis=None,
        )
    if output.strip():
        MarkdownRenderer(config.ui).render(output)
    return exit_code


__all__ = [
    "build_code_exploration_prompt",
    "close_vector_store",
    "cmd_search",
    "code_explorer_preflight",
    "ensure_storage_runtime",
    "format_search_result",
    "make_plugin_manager",
    "make_search_agent_runner",
    "make_vector_store",
    "normalize_query",
    "render_activity",
    "render_status_line",
    "render_status_panel",
    "result_to_json",
    "run_deterministic_search_fallback",
    "run_search",
    "search_agent_binary",
    "search_agent_binary_available",
    "search_agent_prompt",
    "search_output_formatter",
    "sort_results_by_score",
    "status_console",
    "store_label",
]
