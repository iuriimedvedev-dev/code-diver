from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import shutil
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from .config import AppConfig, ConfigLoader
from .config.embedding_profile_registry import EmbeddingProfileRegistry
from .agent import DirectIndexingOrchestrator, DirectSearchOrchestrator
from .agent.h3_search_tool_handler import H3SearchToolHandler
from .agent.rerank_tool_handler import RerankToolHandler
from .ai_indexing import AiCodebaseScanner, HybridCodebaseScanner
from .benchmarks import BenchmarkAssetService, BenchmarkProfile, BenchmarkProfileRegistry
from .domain import CodeItemIndexKindResolver, EvalResult, SearchResult
from .env import EnvFileLoader
from .experiments import ExperimentRunner
from .generation import create_generation_provider
from .graph import CodeGraphBuilder, CodeGraphStore
from .inspection import GrepService, ReadExcerptService, RgService, SymbolsService, TreeService
from .metrics import ClickHouseClient, ClickHouseDockerClient, ClickHouseMetricsRepository, ExperimentMetricsMapper
from .orchestration import OrchestratedCodebaseScanner
from .pi import PiRunner, PiRuntimeManager, PiSessionOptions
from .plugins import PluginManager
from .providers import create_embedding_provider
from .runtime import EmbeddingRuntimeManager, QdrantRuntimeManager, RuntimeConfigStore, RuntimeSetupWizard
from .settings import (
    CommandName,
    Defaults,
    EmbeddingProviderId,
    OptionName,
    SchemaKey,
    VectorStoreProviderId,
)
from .services import (
    CandidateFileScanner,
    CodebaseScanner,
    DatasetLoader,
    EphemeralDeepIndexService,
    GraphIndexingService,
    IndexCollectionResolver,
    IndexCompositionAnalyzer,
    IndexingOptions,
    IndexingService,
    LocalEvalDatasetGenerator,
    SelectedCodeItemBuilder,
    SelectedIndexPayloadParser,
    SelectedIndexingService,
)
from .services.codebase_scanner import DEFAULT_EXCLUDES
from .services.eval_case_bucket_classifier import EvalCaseBucketClassifier
from .services.evaluation_service import EvaluationService
from .services.evaluation_statistics import EvaluationStatistics
from .strategies import RetrievalStrategyFactory
from .store import create_vector_store
from .tracing import TraceLogger
from .ui import EditorOpener, EvaluationRenderer, MarkdownRenderer, SearchRenderer, TraceMonitor


ADVANCED_COMMANDS = {
    CommandName.ASK.value,
    CommandName.CHAT.value,
    CommandName.EVALUATE_INDEXING.value,
    CommandName.EVALUATE_SEARCH_TOOLS.value,
    CommandName.EXPERIMENT.value,
    CommandName.GREP.value,
    CommandName.INDEX_SELECTED.value,
    CommandName.MONITOR.value,
    CommandName.OPEN.value,
    CommandName.READ.value,
    CommandName.RG.value,
    CommandName.SYMBOLS.value,
    CommandName.TREE.value,
}

INDEX_MAINTENANCE_COMMANDS = {"clear", "prune", "reset"}


def status_console() -> Console:
    return Console(stderr=True, color_system="auto")


def render_status_panel(title: str, rows: list[tuple[str, object]], border_style: str = "cyan") -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    for key, value in rows:
        table.add_row(key, str(value))
    status_console().print(Panel(table, title=f"[bold]{title}[/bold]", border_style=border_style, padding=(0, 1)))


def render_status_line(message: str, style: str = "cyan") -> None:
    status_console().print(f"[{style}]\\[code-diver][/{style}] {message}")


@contextlib.contextmanager
def render_activity(message: str, enabled: bool = True, style: str = "cyan"):
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
        progress.add_task("working", total=None)
        yield


def ensure_storage_runtime(config: AppConfig, progress: bool = True) -> None:
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
        render_status_line(f"started local Qdrant: {config.storage.qdrant.url}", "green")


def make_vector_store(config: AppConfig, progress: bool = False):
    ensure_storage_runtime(config, progress=progress)
    return create_vector_store(config)


def main(argv: list[str] | None = None) -> int:
    normalized = normalize_argv(argv)
    include_advanced = bool(
        normalized
        and (OptionName.HELP_ALL.value in normalized or any(token in ADVANCED_COMMANDS for token in normalized))
    )
    parser = build_parser(include_advanced=include_advanced)
    if include_advanced:
        normalized = [token for token in normalized or [] if token != OptionName.HELP_ALL.value]
        if not normalized:
            parser.print_help()
            return 0
    args = parser.parse_args(normalized)
    try:
        config = ConfigLoader().load(args.config)
        config = apply_runtime_config(args, config)
        EnvFileLoader().load(config.env_file.path, config.env_file.override)
        return int(args.func(args, config))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser(include_advanced: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code-diver", description="Config-first codebase RAG CLI.")
    parser.add_argument(OptionName.CONFIG.value, type=Path, default=None, help="YAML config path.")
    parser.add_argument(OptionName.ROOT.value, type=Path, default=None, help="Repository root for built-in profiles.")
    parser.add_argument(
        OptionName.HELP_ALL.value,
        action="store_true",
        help="Show advanced inspection, agent, and research commands.",
    )
    command_metavar = None if include_advanced else "{init,index,search,evaluate}"
    subparsers = parser.add_subparsers(dest="command", required=True, metavar=command_metavar)

    init = subparsers.add_parser(CommandName.INIT.value, help="Interactively configure local model runtimes.")
    init.add_argument(
        "--embedding",
        choices=EmbeddingProfileRegistry().keys(),
        default=None,
        help="Embedding extractor profile to configure.",
    )
    init.add_argument("--yes", action="store_true", help="Accept defaults and install without prompting.")
    init.add_argument(
        "--platform",
        choices=["apple-metal", "nvidia-cuda", "amd-rocm", "cpu", "api", "external"],
        default=None,
        help="Hardware/runtime platform used to filter model choices.",
    )
    init.add_argument(
        "--runtime",
        choices=["host-uv", "external"],
        default=None,
        help="Model runtime backend: managed host uv subprocess or external/container endpoint.",
    )
    init.add_argument("--skip-install", action="store_true", help="Write config without installing vLLM/MLX.")
    init.add_argument("--start", action="store_true", help="Start the configured local embedding server after setup.")
    init.set_defaults(func=cmd_init)

    index = subparsers.add_parser(CommandName.INDEX.value, help="Index repository code into the configured artifact.")
    index.add_argument("index_root", nargs="?", type=Path, default=None)
    index_mode = index.add_mutually_exclusive_group()
    index_mode.add_argument(
        "--update-index",
        action="store_true",
        help="Replace only the current repo/model collection if it already exists.",
    )
    index_mode.add_argument(
        "--override-repo",
        action="store_true",
        help="Delete other Qdrant collections for this repository before indexing.",
    )
    index.add_argument("--all", action="store_true", help="With `index clear`, delete all Code Diver index collections.")
    index.add_argument("--no-progress", action="store_true", help="Disable indexing progress bars.")
    index.add_argument("-q", "--quiet", action="store_true", help="Only print the final indexing summary.")
    index.set_defaults(func=cmd_index)

    search = subparsers.add_parser(CommandName.SEARCH.value, help="Ask the code exploration agent.")
    search.add_argument("query", nargs="*")
    search.add_argument(OptionName.LIMIT.value, type=int, default=None)
    search.add_argument(
        "-j",
        OptionName.JSON.value,
        action="store_true",
        help="Return raw deterministic retrieval results instead of invoking the agent.",
    )
    search.add_argument("-i", "--interactive", action="store_true", help="Open an interactive Search agent.")
    search.set_defaults(func=cmd_search)

    evaluate = subparsers.add_parser(CommandName.EVALUATE.value, help="Evaluate retrieval on the configured dataset.")
    evaluate.add_argument(
        OptionName.BENCHMARK.value,
        choices=BenchmarkProfileRegistry().names(),
        default=None,
        help="Use a reproducible benchmark profile.",
    )
    evaluate.add_argument(OptionName.DATASET.value, type=Path, default=None)
    evaluate.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate.add_argument(OptionName.JSON.value, action="store_true")
    evaluate.add_argument(OptionName.REINDEX.value, action="store_true")
    evaluate.add_argument(
        "--generate-dataset",
        action="store_true",
        help="Generate a small repository-local evaluation dataset before running evaluation.",
    )
    evaluate.add_argument(
        "--cases",
        type=int,
        default=50,
        help="Number of local evaluation cases to generate with --generate-dataset.",
    )
    evaluate.add_argument(OptionName.YES.value, action="store_true", help="Allow benchmark asset downloads without asking.")
    evaluate.set_defaults(func=cmd_evaluate)

    if include_advanced:
        add_advanced_parsers(subparsers)

    return parser


def add_advanced_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    index_selected = subparsers.add_parser(
        CommandName.INDEX_SELECTED.value,
        help="Index agent-selected file ranges from a JSON payload on stdin.",
    )
    index_selected.add_argument(OptionName.JSON.value, action="store_true")
    index_selected.set_defaults(func=cmd_index_selected)

    tree = subparsers.add_parser(CommandName.TREE.value, help="Print a gitignore-aware repository tree.")
    tree.add_argument(OptionName.PATH.value, default=None)
    tree.add_argument(OptionName.LIMIT.value, type=int, default=200)
    tree.add_argument("--depth", type=int, default=3)
    tree.set_defaults(func=cmd_tree)

    grep = subparsers.add_parser(CommandName.GREP.value, help="Literal gitignore-aware text search.")
    grep.add_argument("pattern")
    grep.add_argument(OptionName.PATH.value, default=None)
    grep.add_argument(OptionName.LIMIT.value, type=int, default=100)
    grep.set_defaults(func=cmd_grep)

    rg = subparsers.add_parser(CommandName.RG.value, help="Regex gitignore-aware text search via rg.")
    rg.add_argument("pattern")
    rg.add_argument(OptionName.PATH.value, default=None)
    rg.add_argument(OptionName.LIMIT.value, type=int, default=100)
    rg.set_defaults(func=cmd_rg)

    read = subparsers.add_parser(CommandName.READ.value, help="Read a bounded, gitignore-aware file excerpt.")
    read.add_argument("file")
    read.add_argument(OptionName.START_LINE.value, type=int, default=1)
    read.add_argument(OptionName.LINES.value, type=int, default=80)
    read.set_defaults(func=cmd_read)

    symbols = subparsers.add_parser(CommandName.SYMBOLS.value, help="List parsed source symbols.")
    symbols.add_argument(OptionName.PATH.value, default=None)
    symbols.add_argument(OptionName.LIMIT.value, type=int, default=200)
    symbols.set_defaults(func=cmd_symbols)

    open_result = subparsers.add_parser(
        CommandName.OPEN.value,
        help="Open the best search result in the configured editor.",
    )
    open_result.add_argument("query", nargs="+")
    open_result.add_argument(OptionName.RANK.value, type=int, default=1)
    open_result.set_defaults(func=cmd_open)

    chat = subparsers.add_parser(CommandName.CHAT.value, help="Start or resume the interactive Search agent.")
    chat.add_argument("prompt", nargs="*", default=[])
    chat.add_argument("--resume", "-r", action="store_true", help="Select a saved Code Diver chat session to resume.")
    chat.add_argument("--continue", "-c", dest="continue_session", action="store_true", help="Continue the last session.")
    chat.add_argument(OptionName.SESSION.value, default=None, help="Resume a specific Pi session path or partial id.")
    chat.add_argument(OptionName.SESSION_ID.value, default=None, help="Use an exact project session id.")
    chat.add_argument(OptionName.SESSION_DIR.value, type=Path, default=None, help="Override Code Diver chat session storage.")
    chat.add_argument(OptionName.NAME.value, default=None, help="Set the session display name.")
    chat.add_argument(OptionName.TOOLSET.value, default=None)
    chat.add_argument(OptionName.HYPOTHESIS.value, default=None)
    chat.set_defaults(func=cmd_chat)

    ask = subparsers.add_parser(CommandName.ASK.value, help="Ask the Search agent once.")
    ask.add_argument("query", nargs="+")
    ask.add_argument(OptionName.TOOLSET.value, default=None)
    ask.add_argument(OptionName.HYPOTHESIS.value, default=None)
    ask.set_defaults(func=cmd_ask)

    evaluate_indexing = subparsers.add_parser(
        CommandName.EVALUATE_INDEXING.value,
        help="Run direct AI indexing hypotheses, then evaluate retrieval metrics.",
    )
    evaluate_indexing.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate_indexing.add_argument(OptionName.HYPOTHESIS.value, action="append", default=[])
    evaluate_indexing.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate_indexing.add_argument(OptionName.JSON.value, action="store_true")
    evaluate_indexing.set_defaults(func=cmd_evaluate_indexing)

    evaluate_search_tools = subparsers.add_parser(
        CommandName.EVALUATE_SEARCH_TOOLS.value,
        help="Run direct AI search-tool hypotheses on the configured dataset.",
    )
    evaluate_search_tools.add_argument(OptionName.DATASET.value, type=Path, default=None)
    evaluate_search_tools.add_argument(OptionName.LIMIT.value, type=int, default=None)
    evaluate_search_tools.add_argument(
        "--cases",
        type=int,
        default=None,
        help="Evaluate only the first N dataset cases. --limit remains the retrieval top-k.",
    )
    evaluate_search_tools.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Run direct search-tool cases concurrently. Defaults to evaluation.workers.",
    )
    evaluate_search_tools.add_argument(OptionName.HYPOTHESIS.value, action="append", default=[])
    evaluate_search_tools.add_argument(OptionName.DETAILS.value, action="store_true")
    evaluate_search_tools.add_argument(OptionName.JSON.value, action="store_true")
    evaluate_search_tools.set_defaults(func=cmd_evaluate_search_tools)

    experiment = subparsers.add_parser(
        CommandName.EXPERIMENT.value,
        help="Run configured retrieval hypotheses and optionally record metrics.",
    )
    experiment.add_argument(OptionName.HYPOTHESIS.value, action="append", default=[])
    experiment.add_argument(OptionName.JSON.value, action="store_true")
    experiment.add_argument(OptionName.REINDEX.value, action="store_true")
    experiment.set_defaults(func=cmd_experiment)

    monitor = subparsers.add_parser(CommandName.MONITOR.value, help="Show a live Rich view of a JSONL trace.")
    monitor.add_argument("--trace", type=Path, default=None)
    monitor.add_argument("--refresh", type=float, default=0.5)
    monitor.add_argument("--max-events", type=int, default=200)
    monitor.set_defaults(func=cmd_monitor)


def normalize_argv(argv: list[str] | None) -> list[str] | None:
    if argv is None:
        raw = list(sys.argv[1:])
    else:
        raw = list(argv)
    normalized: list[str] = []
    config_tokens: list[str] = []
    index = 0
    while index < len(raw):
        token = raw[index]
        if token in {OptionName.CONFIG.value, OptionName.ROOT.value} and index + 1 < len(raw):
            config_tokens.extend([token, raw[index + 1]])
            index += 2
            continue
        if token.startswith(f"{OptionName.CONFIG.value}=") or token.startswith(f"{OptionName.ROOT.value}="):
            config_tokens.append(token)
            index += 1
            continue
        normalized.append(token)
        index += 1
    return [*config_tokens, *normalized]


def apply_runtime_config(args: argparse.Namespace, config: AppConfig) -> AppConfig:
    root = runtime_root(args)
    if should_apply_builtin_h5(args):
        config = apply_builtin_h5(config)
    if root is not None:
        config = replace(config, root=root)
    embedding_profile = getattr(args, "embedding", None)
    if embedding_profile:
        config = apply_embedding_profile(config, embedding_profile, announce=False)
    elif should_apply_configured_runtime_profile(args):
        config = apply_configured_runtime_profile(config)
    if getattr(args, "command", None) != CommandName.INIT.value:
        config = IndexCollectionResolver().resolve(config)
    return config


def apply_embedding_profile(config: AppConfig, profile_key: str, announce: bool = True) -> AppConfig:
    profile = EmbeddingProfileRegistry().get(profile_key)
    if announce:
        render_status_line(f"embedding extractor: {profile.label}", "green")
        if profile.startup_hint:
            render_status_line(f"local server expected: {profile.startup_hint}", "yellow")
    return replace(config, embedding=profile.config)


def apply_configured_runtime_profile(config: AppConfig) -> AppConfig:
    store = RuntimeConfigStore()
    if not store.exists():
        return config
    runtime = store.load()
    return apply_embedding_profile(config, runtime.embedding_profile, announce=False)


def should_apply_configured_runtime_profile(args: argparse.Namespace) -> bool:
    if getattr(args, "command", None) == CommandName.INIT.value:
        return False
    config_path = getattr(args, "config", None)
    if config_path is None:
        return True
    return is_default_config_path(config_path)


def is_default_config_path(path: Path) -> bool:
    return path.resolve() == Defaults.CONFIG_PATH.resolve()


def runtime_root(args: argparse.Namespace) -> Path | None:
    command_root = getattr(args, "index_root", None)
    if is_index_maintenance_command(command_root):
        return getattr(args, "root", None)
    if command_root is not None:
        return command_root
    global_root = getattr(args, "root", None)
    return global_root if global_root is not None else None


def is_index_maintenance_command(value: object) -> bool:
    return value is not None and str(value) in INDEX_MAINTENANCE_COMMANDS


def should_apply_builtin_h5(args: argparse.Namespace) -> bool:
    if getattr(args, "benchmark", None):
        return False
    if getattr(args, "config", None) is not None:
        return False
    return not Defaults.CONFIG_PATH.exists()


def apply_builtin_h5(config: AppConfig) -> AppConfig:
    scanner = replace(
        config.scanner,
        line_chunks=False,
        chunk_lines=220,
        structural_chunks=False,
        symbol_chunks=False,
        symbol_body=False,
        file_summary_chunks=True,
        file_manifest_chunks=True,
        max_symbols_per_file=96,
    )
    search = replace(config.search, strategy="hybrid_rerank", limit=10, preview_lines=10)
    hybrid = replace(
        config.hybrid_search,
        candidate_limit=280,
        lexical_candidate_limit=900,
        vector_weight=0.42,
        lexical_weight=0.26,
        path_weight=0.12,
        symbol_weight=0.10,
        symbol_match_weight=0.10,
        graph_weight=0.0,
        file_vote_weight=0.06,
        graph_depth=0,
        graph_neighbor_limit=0,
        vector_kind_limits={"file_summary": 170, "file_manifest": 170},
        vector_kind_multipliers={"file_summary": 1.0, "file_manifest": 1.08},
        routing_enabled=True,
        lexical_scoring="bm25",
        fusion="weighted",
        preserve_vector_top=True,
        vector_top_score_margin=0.03,
        item_kind_weights={"file_summary": 1.0, "file_manifest": 1.08},
        min_token_length=3,
    )
    llm_rerank = replace(
        config.llm_rerank,
        candidate_limit=30,
        rerank_limit=10,
        max_preview_chars=700,
        mode="precision",
        include_reasons=False,
        preserve_top_candidate=False,
        retry_attempts=3,
        retry_base_delay_seconds=1.0,
        retry_max_delay_seconds=8.0,
    )
    generation = replace(
        config.generation,
        provider=Defaults.GENERATION_PROVIDER,
        model="gemini-3.1-flash-lite",
        fallback_models=[],
        location="global",
        temperature=0.0,
        thinking_budget=256,
        api_version="v1",
        timeout_ms=30_000,
    )
    graph = replace(
        config.graph,
        ast_enabled=False,
        reference_edges_enabled=False,
        call_edges_enabled=False,
        expansion_depth=0,
        neighbor_limit=0,
    )
    trace = replace(config.trace, include_prompts=True)
    return replace(
        config,
        scanner=scanner,
        search=search,
        hybrid_search=hybrid,
        llm_rerank=llm_rerank,
        generation=generation,
        graph=graph,
        trace=trace,
    )


def apply_builtin_pure_h3(config: AppConfig) -> AppConfig:
    return apply_builtin_h5(config)


def cmd_index(args: argparse.Namespace, config: AppConfig) -> int:
    if is_index_maintenance_command(getattr(args, "index_root", None)):
        return cmd_index_clear(args, config)
    if bool(getattr(args, "all", False)):
        raise ValueError("`--all` is only supported with `code-diver index clear`.")
    progress = not bool(getattr(args, "no_progress", False) or getattr(args, "quiet", False))
    ensure_storage_runtime(config, progress=progress)
    prepare_index_collection(args, config, progress=progress)
    if progress:
        render_status_panel(
            "Index",
            [
                ("root", config.root.resolve()),
                ("store", store_label(config)),
                ("mode", index_write_mode_label(args)),
                ("scanner", config.indexing.mode),
                ("profile", index_profile_label(config)),
                ("embeds", index_content_label(config)),
                ("graph", graph_label(config)),
                ("include", config.scanner.include or ["default-code-files"]),
                ("exclude", f"{len(config.scanner.exclude)} configured patterns"),
            ],
        )
    with render_activity(embedding_activity_message(config), enabled=progress):
        provider = make_embedding_provider(config)
    if progress:
        render_status_panel(
            "Embedding",
            [
                ("provider", provider.name),
                ("model", provider.model),
                ("endpoint", config.embedding.url or config.embedding.location or "provider default"),
                ("dimensions", provider.dimensions or "auto"),
                ("batch size", config.embedding.batch_size),
                ("workers", config.embedding.workers),
                ("max chars", config.embedding.max_input_chars or "provider default"),
            ],
            border_style="magenta",
        )
    indexing_service = make_indexing_service(config, progress=progress)
    try:
        items = indexing_service.build(
            config.root,
            provider=provider,
            plugin_config={"config": config},
        )
        if config.graph.enabled:
            with render_activity(graph_activity_message(config, len(items)), enabled=progress):
                GraphIndexingService(
                    CodeGraphBuilder(
                        ast_enabled=config.graph.ast_enabled,
                        reference_edges_enabled=config.graph.reference_edges_enabled,
                        call_edges_enabled=config.graph.call_edges_enabled,
                    ),
                    CodeGraphStore(config.graph.artifact),
                ).build(
                    config.root,
                    items,
                )
            if progress:
                render_status_line(f"saved graph artifact: {config.graph.artifact}", "green")
        print(
            f"Indexed {len(items)} items -> {store_label(config)} "
            f"({provider.name}, model={provider.model}, dimensions={provider.dimensions})"
        )
        print(format_index_composition(items))
    except KeyboardInterrupt:
        render_status_line("indexing interrupted; staged index writes were discarded", "yellow")
        raise
    finally:
        close_vector_store(indexing_service.vector_store)
    return 0


def cmd_index_clear(args: argparse.Namespace, config: AppConfig) -> int:
    if bool(getattr(args, "update_index", False) or getattr(args, "override_repo", False)):
        raise ValueError("`index clear` cannot be combined with `--update-index` or `--override-repo`.")
    if config.storage.provider != VectorStoreProviderId.QDRANT.value:
        raise ValueError("`index clear` is only supported for Qdrant storage.")
    progress = not bool(getattr(args, "no_progress", False) or getattr(args, "quiet", False))
    ensure_storage_runtime(config, progress=progress)
    prefix = Defaults.QDRANT_COLLECTION if bool(getattr(args, "all", False)) else current_repo_collection_prefix(config)
    scope = "all Code Diver index collections" if bool(getattr(args, "all", False)) else "current repository collections"
    if progress:
        render_status_panel(
            "Index Clear",
            [
                ("scope", scope),
                ("prefix", prefix),
                (
                    "store",
                    config.storage.qdrant.url if config.storage.qdrant.location is None else config.storage.qdrant.location,
                ),
            ],
            border_style="yellow",
        )
    vector_store = make_vector_store(config)
    try:
        with render_activity(f"deleting Qdrant index collections: {prefix}", enabled=progress, style="yellow"):
            deleted = vector_store.delete_collections_with_prefix(prefix)
    finally:
        close_vector_store(vector_store)
    print(f"Deleted {len(deleted)} Qdrant collection entries for prefix `{prefix}`.")
    if deleted and not bool(getattr(args, "quiet", False)):
        for name in deleted:
            print(f"  {name}")
    return 0


def prepare_index_collection(args: argparse.Namespace, config: AppConfig, progress: bool = True) -> None:
    if config.storage.provider != VectorStoreProviderId.QDRANT.value:
        return
    vector_store = make_vector_store(config)
    try:
        if bool(getattr(args, "override_repo", False)):
            prefix = current_repo_collection_prefix(config)
            with render_activity(f"removing existing Qdrant collections for repo prefix: {prefix}", enabled=progress):
                deleted = vector_store.delete_collections_with_prefix(prefix)
            if progress:
                render_status_line(f"removed {len(deleted)} repo collection entries", "yellow")
            return
        if bool(getattr(args, "update_index", False) or getattr(args, "reindex", False)):
            return
        if vector_store.exists():
            raise RuntimeError(
                f"Index collection already exists: {config.storage.qdrant.collection}. "
                "Use `--update-index` to replace only this collection, or `--override-repo` "
                "to delete all collections for this repository before indexing."
            )
    finally:
        close_vector_store(vector_store)


def current_repo_collection_prefix(config: AppConfig) -> str:
    collection = config.storage.qdrant.collection
    marker = "__emb_"
    if marker in collection:
        return collection.split(marker, 1)[0]
    return collection


def index_write_mode_label(args: argparse.Namespace) -> str:
    if bool(getattr(args, "override_repo", False)):
        return "override repo collections"
    if bool(getattr(args, "update_index", False) or getattr(args, "reindex", False)):
        return "update current collection"
    return "create new collection"


def embedding_activity_message(config: AppConfig) -> str:
    model = config.embedding.model or "provider default"
    provider = config.embedding.provider or Defaults.EMBEDDING_PROVIDER
    if config.embedding.provider == EmbeddingProviderId.OPENAI_COMPATIBLE.value:
        return (
            "checking embedding runtime from init config and preparing local client: "
            f"model={model} endpoint={config.embedding.url}"
        )
    if config.embedding.provider in {"gemini", "vertex"}:
        location = f" location={config.embedding.location}" if config.embedding.location else ""
        return f"creating API embedding client: provider={provider} model={model}{location}"
    return f"creating embedding client: provider={provider} model={model}"


def index_profile_label(config: AppConfig) -> str:
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H5 file locator"
    return "custom"


def index_content_label(config: AppConfig) -> str:
    enabled: list[str] = []
    if config.scanner.file_summary_chunks:
        enabled.append("file summaries")
    if config.scanner.file_manifest_chunks:
        enabled.append("file manifests")
    if config.scanner.line_chunks:
        enabled.append("line chunks")
    if config.scanner.structural_chunks:
        enabled.append("AST chunks")
    if config.scanner.symbol_chunks:
        enabled.append("symbols")
    return ", ".join(enabled) if enabled else "scanner output"


def graph_label(config: AppConfig) -> str:
    if not config.graph.enabled:
        return "disabled"
    enabled = []
    if config.graph.ast_enabled:
        enabled.append("AST")
    if config.graph.reference_edges_enabled:
        enabled.append("references")
    if config.graph.call_edges_enabled:
        enabled.append("calls")
    suffix = ", ".join(enabled) if enabled else "containment"
    return f"enabled ({suffix})"


def graph_activity_message(config: AppConfig, item_count: int) -> str:
    return (
        "building graph artifact from indexed items: "
        f"items={item_count} artifact={config.graph.artifact} {graph_label(config)}"
    )


def cmd_init(args: argparse.Namespace, config: AppConfig) -> int:
    if bool(args.skip_install):
        render_status_line("skipping Search agent npm dependency install because --skip-install was passed", "yellow")
    else:
        with render_activity("installing Search agent npm dependencies from package-lock/package.json", style="blue"):
            PiRuntimeManager().install()
        render_status_line("Search agent npm runtime is installed", "green")
    RuntimeSetupWizard().run(
        profile_key=args.embedding,
        platform=args.platform,
        backend=args.runtime,
        install=False if args.skip_install else None,
        start=bool(args.start),
        yes=bool(args.yes),
    )
    try:
        ensure_storage_runtime(config, progress=True)
    except Exception as exc:
        render_status_line(f"storage runtime was not started during init: {exc}", "yellow")
    return 0


def cmd_index_selected(args: argparse.Namespace, config: AppConfig) -> int:
    selections = SelectedIndexPayloadParser().parse(sys.stdin.read())
    built = SelectedCodeItemBuilder(
        config.root,
        config.scanner.chunk_lines,
        inspection_exclude_patterns(config),
    ).build(selections)
    if not built.items:
        payload = {"indexed": 0, "skipped": built.skipped, "store": store_label(config), "items": []}
        print(json.dumps(payload, indent=2) if args.json else "Indexed 0 selected items.")
        return 0
    provider = make_embedding_provider(config)
    service = SelectedIndexingService(
        make_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            progress=True,
        ),
        make_trace_logger(config),
    )
    items = service.build(config.root, provider, built.items)
    if config.graph.enabled:
        GraphIndexingService(
            CodeGraphBuilder(
                ast_enabled=config.graph.ast_enabled,
                reference_edges_enabled=config.graph.reference_edges_enabled,
                call_edges_enabled=config.graph.call_edges_enabled,
            ),
            CodeGraphStore(config.graph.artifact),
        ).build(config.root, items)
    close_vector_store(service.vector_store)
    payload = {
        "indexed": len(items),
        "skipped": built.skipped,
        "store": store_label(config),
        "items": [item.to_json() for item in items],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Indexed {len(items)} selected items -> {store_label(config)}")
        for skipped in built.skipped:
            print(f"skipped: {skipped}", file=sys.stderr)
    return 0


def cmd_search(args: argparse.Namespace, config: AppConfig) -> int:
    query = normalize_query(args.query)
    if not query and not args.interactive:
        print("error: search query is required unless -i/--interactive is used.", file=sys.stderr)
        return 1
    if args.json:
        results = run_search(config, query, args.limit or config.search.limit)
        print(json.dumps([result_to_json(result) for result in results], indent=2))
        return 0
    if not args.json:
        if not code_explorer_preflight(config, args.config):
            return 1
    if not search_agent_binary_available(config):
        if args.interactive:
            render_status_panel(
                "Search Agent Unavailable",
                [
                    ("binary", config.pi.binary),
                    ("fix", "install/configure the Search agent runtime, or use non-interactive search"),
                    ("deterministic", f'uv run code-diver --root {config.root} search "{query}" --json'),
                ],
                border_style="red",
            )
            return 1
        return run_deterministic_search_fallback(config, query, args.limit or config.search.limit, config.pi.binary)
    if args.interactive:
        prompt = build_code_exploration_prompt(query) if query else None
        return PiRunner().run_interactive(config, args.config, prompt=prompt)
    with render_activity(
        "running Search agent: planning tool calls, reading bounded excerpts, preparing answer",
        enabled=True,
        style="green",
    ):
        exit_code, output = PiRunner().run_print_capture(
            config,
            args.config,
            build_code_exploration_prompt(query),
            toolset=None,
            hypothesis=None,
        )
    if output.strip():
        MarkdownRenderer(config.ui).render(output)
    return exit_code


def search_agent_binary_available(config: AppConfig) -> bool:
    binary = config.pi.binary
    return bool(shutil.which(binary) or Path(binary).exists())


def run_deterministic_search_fallback(config: AppConfig, query: str, limit: int, missing_binary: str) -> int:
    render_status_panel(
        "Deterministic Search Fallback",
        [
            ("reason", f"Search agent binary is not available: {missing_binary}"),
            ("mode", "retrieval only; no LLM explanation"),
            ("json", f'uv run code-diver --root {config.root} search "{query}" --json'),
        ],
        border_style="yellow",
    )
    with render_activity("running deterministic retrieval over the existing index", enabled=True, style="yellow"):
        results = run_search(config, query, limit)
    SearchRenderer(config.root, config.ui, config.search.preview_lines).render(query, results)
    return 0


def code_explorer_preflight(config: AppConfig, config_path: Path | None) -> bool:
    render_status_panel(
        "Search Agent",
        [
            ("root", config.root.resolve()),
            ("config", (config_path or Defaults.CONFIG_PATH).resolve()),
            ("store", store_label(config)),
            ("model", config.pi.model or "default"),
            ("tools", ", ".join(config.pi.tools) if config.pi.tools else "(none configured)"),
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
                    ("raw check", f'uv run code-diver --root {config.root} search "your query" --json'),
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


def build_code_exploration_prompt(query: str) -> str:
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


def cmd_tree(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        TreeService(config.root, inspection_exclude_patterns(config)).render(
            path=args.path, max_depth=args.depth, limit=args.limit
        )
    )
    return 0


def cmd_grep(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        GrepService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(args.pattern, path=args.path, limit=args.limit)
    )
    return 0


def cmd_rg(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        RgService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).search(args.pattern, path=args.path, limit=args.limit)
    )
    return 0


def cmd_read(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        ReadExcerptService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(
            args.file, start_line=args.start_line, lines=args.lines
        )
    )
    return 0


def cmd_symbols(args: argparse.Namespace, config: AppConfig) -> int:
    print(
        SymbolsService(
            config.root,
            inspection_exclude_patterns(config),
            config.scanner.max_file_bytes,
        ).render(path=args.path, limit=args.limit)
    )
    return 0


def cmd_open(args: argparse.Namespace, config: AppConfig) -> int:
    rank = max(int(args.rank), 1)
    limit = max(rank, config.search.limit)
    results = run_search(config, normalize_query(args.query), limit)
    if not results:
        print("No search results.")
        return 1
    if rank > len(results):
        print(f"Only {len(results)} search results available.")
        return 1
    result = results[rank - 1]
    command_line = EditorOpener(config.root, config.ui).open(result)
    location = result.item.path
    if result.item.start_line is not None:
        location = f"{location}:{result.item.start_line}"
    print(f"Opened {location} with: {' '.join(command_line)}")
    return 0


def cmd_ask(args: argparse.Namespace, config: AppConfig) -> int:
    return PiRunner().run_print(
        config,
        args.config,
        normalize_query(args.query),
        toolset=args.toolset,
        hypothesis=args.hypothesis,
    )


def cmd_chat(args: argparse.Namespace, config: AppConfig) -> int:
    prompt, session = chat_prompt_and_session(args, config)
    return PiRunner().run_interactive(
        config,
        args.config,
        prompt,
        toolset=args.toolset,
        hypothesis=args.hypothesis,
        session=session,
    )


def chat_prompt_and_session(args: argparse.Namespace, config: AppConfig) -> tuple[str | None, PiSessionOptions]:
    words = list(getattr(args, "prompt", []) or [])
    resume = bool(getattr(args, "resume", False))
    continue_session = bool(getattr(args, "continue_session", False))
    session = getattr(args, "session", None)
    session_id = getattr(args, "session_id", None)

    if words and words[0] in {"resume", "continue"}:
        mode = words.pop(0)
        resume = resume or mode == "resume"
        continue_session = continue_session or mode == "continue"
        if words and not session and not session_id:
            session = words.pop(0)

    prompt = normalize_query(words) if words else None
    session_dir = getattr(args, "session_dir", None) or config.pi.session_dir
    return prompt, PiSessionOptions(
        session_dir=session_dir,
        resume=resume,
        continue_session=continue_session,
        session=session,
        session_id=session_id,
        name=getattr(args, "name", None),
    )


def cmd_evaluate(args: argparse.Namespace, config: AppConfig) -> int:
    benchmark = resolve_benchmark_profile(args)
    if benchmark is not None and args.config is None and benchmark.config_path is not None:
        config = ConfigLoader().load(benchmark.config_path)
        EnvFileLoader().load(config.env_file.path, config.env_file.override)
    if benchmark is not None:
        BenchmarkAssetService().ensure(benchmark, assume_yes=bool(getattr(args, "yes", False)))

    dataset = args.dataset or (benchmark.dataset if benchmark is not None else config.evaluation.dataset)
    generated_cases: list[dict[str, Any]] | None = None
    if bool(getattr(args, "generate_dataset", False)):
        dataset = args.dataset or config.root / ".code-diver" / "eval" / "local_eval.jsonl"
        generated_cases = generate_local_eval_dataset(config, dataset, int(getattr(args, "cases", 50)))
        if not bool(args.json):
            render_status_line(f"generated local eval dataset: {dataset} ({len(generated_cases)} cases)", "green")

    vector_store = make_vector_store(config, progress=not bool(args.json))
    if args.reindex or not vector_store.exists():
        if args.json:
            with contextlib.redirect_stdout(sys.stderr):
                cmd_index(args, config)
        else:
            cmd_index(args, config)
        vector_store = make_vector_store(config, progress=not bool(args.json))

    limit = args.limit or config.evaluation.limit
    provider = make_embedding_provider(config, vector_store.metadata())
    plugin_manager = make_plugin_manager(config)
    cases = DatasetLoader().load(dataset)
    for case in cases:
        case.query = plugin_manager.prepare_query(case.query)

    strategy = make_retrieval_strategy(config, provider, vector_store)
    settings = evaluation_settings(config, dataset, limit, args.config or (benchmark.config_path if benchmark else None))
    if not bool(args.json):
        render_status_panel(
            "Evaluate",
            [
                ("cases", len(cases)),
                ("limit", limit),
                ("workers", config.evaluation.workers),
                ("strategy", config.search.strategy),
                ("ranker", f"{settings['ranker provider']}:{settings['ranker model']}"),
                ("dataset", dataset),
            ],
            border_style="green",
        )
    progress_callback = None
    if not bool(args.json):
        progress = Progress(
            SpinnerColumn("dots"),
            TextColumn("[cyan]\\[code-diver][/cyan] evaluating cases"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=status_console(),
        )
        with progress:
            task_id = progress.add_task("cases", total=len(cases))

            def progress_callback(completed: int, total: int) -> None:
                progress.update(task_id, total=total, completed=completed)

            metrics, results = EvaluationService(strategy, trace_logger=make_trace_logger(config)).evaluate(
                cases,
                limit,
                workers=config.evaluation.workers,
                progress_callback=progress_callback,
            )
    else:
        metrics, results = EvaluationService(strategy, trace_logger=make_trace_logger(config)).evaluate(
            cases,
            limit,
            workers=config.evaluation.workers,
        )
    if args.json:
        print(
            json.dumps(
                {
                    "benchmark": benchmark.to_json() if benchmark is not None else None,
                    "config": str(args.config or (benchmark.config_path if benchmark is not None else Defaults.CONFIG_PATH)),
                    "dataset": str(dataset),
                    "settings": settings,
                    "generated_dataset": {
                        "path": str(dataset),
                        "cases": len(generated_cases),
                    }
                    if generated_cases is not None
                    else None,
                    "limit": limit,
                    "metrics": metrics,
                    "results": [eval_result_to_json(result) for result in results],
                },
                indent=2,
            )
        )
        return 0

    EvaluationRenderer(config.ui.color).render(
        metrics,
        results,
        benchmark=benchmark.to_json() if benchmark is not None else None,
        settings=settings,
        details=args.details,
    )
    return 0


def evaluation_settings(config: AppConfig, dataset: Path, limit: int, config_path: Path | None) -> dict[str, Any]:
    return {
        "config": str(config_path or Defaults.CONFIG_PATH),
        "root": str(config.root),
        "dataset": str(dataset),
        "limit": limit,
        "workers": config.evaluation.workers,
        "store": store_label(config),
        "search strategy": config.search.strategy,
        "index profile": index_profile_label(config),
        "indexed content": index_content_label(config),
        "embedding provider": config.embedding.provider,
        "embedding model": config.embedding.model or "provider default",
        "embedding endpoint": config.embedding.url or config.embedding.location or "provider default",
        "embedding batch/workers": f"{config.embedding.batch_size}/{config.embedding.workers}",
        "embedding max chars": config.embedding.max_input_chars or "provider default",
        "ranker provider": config.generation.provider if config.search.strategy == "hybrid_rerank" else "none",
        "ranker model": config.generation.model if config.search.strategy == "hybrid_rerank" else "none",
        "rerank candidates/top": f"{config.llm_rerank.candidate_limit}/{config.llm_rerank.rerank_limit}",
        "rerank mode": config.llm_rerank.mode,
        "hybrid candidates": config.hybrid_search.candidate_limit,
        "hybrid weights": (
            f"vector={config.hybrid_search.vector_weight}, lexical={config.hybrid_search.lexical_weight}, "
            f"path={config.hybrid_search.path_weight}, symbol={config.hybrid_search.symbol_weight}, "
            f"symbol_match={config.hybrid_search.symbol_match_weight}, file_vote={config.hybrid_search.file_vote_weight}"
        ),
        "graph": graph_label(config),
    }


def resolve_benchmark_profile(args: argparse.Namespace) -> BenchmarkProfile | None:
    name = getattr(args, "benchmark", None)
    if not name:
        return None
    return BenchmarkProfileRegistry().get(str(name))


def cmd_evaluate_indexing(args: argparse.Namespace, config: AppConfig) -> int:
    cases = DatasetLoader().load(config.evaluation.dataset)
    limit = args.limit or config.evaluation.limit
    run_id = uuid.uuid4().hex[:12]
    rows: list[dict[str, Any]] = []
    for hypothesis in indexing_hypotheses(config, args.hypothesis):
        eval_config = config_for_indexing_hypothesis(config, hypothesis.name, run_id)
        log_path = indexing_hypothesis_log_path(config, hypothesis.name, run_id)
        tools = resolve_hypothesis_tools(config, hypothesis.name)
        vector_store = make_vector_store(eval_config)
        embedding_provider = make_embedding_provider(eval_config)
        graph_indexer = make_graph_indexer(eval_config)
        started = perf_counter()
        indexing_result = DirectIndexingOrchestrator(
            root=eval_config.root,
            generation_provider=create_generation_provider(eval_config),
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            allowed_tools=tools,
            max_lines=eval_config.scanner.chunk_lines,
            indexing_options=IndexingOptions(
                embedding_batch_size=eval_config.embedding.batch_size,
                embedding_workers=eval_config.embedding.workers,
                embedding_max_input_chars=eval_config.embedding.max_input_chars,
                progress=True,
            ),
            log_path=log_path,
            include_prompts=eval_config.trace.include_prompts,
            exclude=inspection_exclude_patterns(eval_config),
            max_file_bytes=eval_config.scanner.max_file_bytes,
            graph_indexer=graph_indexer,
        ).run(hypothesis.name, cases)
        close_vector_store(vector_store)
        vector_store = make_vector_store(eval_config)
        indexing_duration_ms = (perf_counter() - started) * 1000
        row: dict[str, Any] = {
            "hypothesis": hypothesis.name,
            "collection": eval_config.storage.qdrant.collection,
            "tools": tools,
            "log_path": str(log_path),
            "orchestrator": "direct",
            "indexing_exit_code": indexing_result.exit_code,
            "indexing_duration_ms": indexing_duration_ms,
            "orchestrator_usage": indexing_result.to_usage_json(),
            "indexed_items": indexing_result.indexed_items,
            "error": indexing_result.error,
        }
        if indexing_result.exit_code != 0:
            close_vector_store(vector_store)
            rows.append(row)
            continue
        if not vector_store.exists():
            row["error"] = "index_not_found"
            close_vector_store(vector_store)
            rows.append(row)
            continue
        count_items = getattr(vector_store, "count_items", None)
        if callable(count_items):
            row["indexed_items"] = count_items()
        provider = make_embedding_provider(eval_config, vector_store.metadata())
        strategy = make_retrieval_strategy(eval_config, provider, vector_store)
        eval_started = perf_counter()
        metrics, results = EvaluationService(strategy, trace_logger=make_trace_logger(eval_config)).evaluate(
            cases,
            limit,
            workers=eval_config.evaluation.workers,
        )
        metrics["evaluation_duration_ms"] = (perf_counter() - eval_started) * 1000
        row["metrics"] = metrics
        if args.details:
            row["results"] = [eval_result_to_json(result) for result in results]
        close_vector_store(vector_store)
        rows.append(row)

    if args.json:
        print(json.dumps({"run_id": run_id, "results": rows}, indent=2))
        return 0

    print(f"run_id: {run_id}")
    for row in rows:
        print()
        print(f"{row['hypothesis']} ({row['collection']})")
        print(f"  tools: {', '.join(row['tools'])}")
        print(f"  log_path: {row['log_path']}")
        print(f"  indexing_duration_ms: {row['indexing_duration_ms']:.1f}")
        usage = row["orchestrator_usage"]
        print(
            "  orchestrator_usage: "
            f"tokens={usage['total_tokens']} "
            f"input={usage['input_tokens']} output={usage['output_tokens']} "
            f"cost=${usage['total_cost']:.6f} tool_calls={usage['tool_calls']}"
        )
        if row.get("error"):
            print(f"  error: {row['error']} exit_code={row['indexing_exit_code']}")
            continue
        print(f"  indexed_items: {row.get('indexed_items', 'unknown')}")
        for name, value in row["metrics"].items():
            print(f"  {name}: {value:.4f}" if isinstance(value, float) else f"  {name}: {value}")
    return 0


def cmd_evaluate_search_tools(args: argparse.Namespace, config: AppConfig) -> int:
    cases = DatasetLoader().load(args.dataset or config.evaluation.dataset)
    if getattr(args, "cases", None) is not None:
        cases = cases[: max(0, int(args.cases))]
    limit = args.limit or config.evaluation.limit
    worker_count = max(1, int(args.workers or config.evaluation.workers or 1))
    run_id = uuid.uuid4().hex[:12]
    rows: list[dict[str, Any]] = []
    for hypothesis in search_tool_hypotheses(config, args.hypothesis):
        eval_config = config_for_search_hypothesis(config, hypothesis)
        tools = resolve_hypothesis_tools(config, hypothesis.name)
        log_path = search_hypothesis_log_path(eval_config, hypothesis.name, run_id)
        search_vector_store = None
        started = perf_counter()
        eval_results: list[Any] = []
        durations_ms: list[float] = []
        usage = empty_agent_usage()
        errors: list[str] = []
        try:
            search_handler = None
            h3_search_handler = None
            generation_provider = create_generation_provider(eval_config)
            rerank_generation_provider = generation_provider
            if getattr(hypothesis, "rerank_generation", None) is not None:
                rerank_generation_provider = create_generation_provider(
                    replace(eval_config, generation=hypothesis.rerank_generation)
                )
            rerank_handler = (
                make_rerank_tool_handler(eval_config, rerank_generation_provider)
                if "code_diver_rerank" in tools
                else None
            )
            ephemeral_search_handler = (
                make_ephemeral_search_tool_handler(eval_config) if "code_diver_ephemeral_search" in tools else None
            )
            if "code_diver_search" in tools or "code_diver_h3_search" in tools:
                search_vector_store = make_vector_store(eval_config)
                search_provider = make_embedding_provider(eval_config, search_vector_store.metadata())
                if "code_diver_search" in tools:
                    search_handler = make_search_tool_handler(
                        make_retrieval_strategy(eval_config, search_provider, search_vector_store)
                    )
                if "code_diver_h3_search" in tools:
                    h3_handler = H3SearchToolHandler(
                        eval_config,
                        search_provider,
                        search_vector_store,
                        exclude=inspection_exclude_patterns(eval_config),
                    )
                    h3_search_handler = h3_handler.search
            orchestrator = DirectSearchOrchestrator(
                root=eval_config.root,
                generation_provider=generation_provider,
                allowed_tools=tools,
                log_path=log_path,
                include_prompts=eval_config.trace.include_prompts,
                search_handler=search_handler,
                h3_search_handler=h3_search_handler,
                rerank_handler=rerank_handler,
                ephemeral_search_handler=ephemeral_search_handler,
                exclude=inspection_exclude_patterns(eval_config),
                max_file_bytes=eval_config.scanner.max_file_bytes,
            )

            def run_case(index: int, case: Any) -> tuple[int, Any, float, dict[str, Any], str | None]:
                case_started = perf_counter()
                try:
                    search_result = orchestrator.search(
                        hypothesis_name=hypothesis.name,
                        case_id=case.id,
                        query=case.query,
                        limit=limit,
                    )
                    duration_ms = (perf_counter() - case_started) * 1000
                    error = f"{case.id}: {search_result.error}" if search_result.error else None
                    return (
                        index,
                        direct_search_eval_result(case, search_result.retrieved, limit),
                        duration_ms,
                        search_result.usage_json(),
                        error,
                    )
                except Exception as exc:
                    duration_ms = (perf_counter() - case_started) * 1000
                    return (
                        index,
                        direct_search_eval_result(case, [], limit),
                        duration_ms,
                        empty_agent_usage(),
                        f"{case.id}: {type(exc).__name__}: {exc}",
                    )

            eval_results_by_index: list[Any | None] = [None] * len(cases)
            durations_by_index: list[float] = [0.0] * len(cases)
            if worker_count == 1 or len(cases) <= 1:
                completed_rows = [run_case(index, case) for index, case in enumerate(cases)]
            else:
                completed_rows = []
                with ThreadPoolExecutor(max_workers=min(worker_count, max(len(cases), 1))) as executor:
                    futures = {
                        executor.submit(run_case, index, case): index
                        for index, case in enumerate(cases)
                    }
                    for future in as_completed(futures):
                        completed_rows.append(future.result())
            for index, eval_result, duration_ms, case_usage, error in completed_rows:
                eval_results_by_index[index] = eval_result
                durations_by_index[index] = duration_ms
                merge_agent_usage(usage, case_usage)
                if error:
                    errors.append(error)
            eval_results = [result for result in eval_results_by_index if result is not None]
            durations_ms = durations_by_index[: len(eval_results)]
        finally:
            if search_vector_store is not None:
                close_vector_store(search_vector_store)
        metrics = direct_search_metrics(eval_results, durations_ms, limit)
        metrics["duration_ms"] = (perf_counter() - started) * 1000
        metrics["evaluation_workers"] = worker_count
        metrics["degraded"] = bool(errors)
        metrics["degraded_cases"] = len(errors)
        metrics["degraded_case_rate"] = len(errors) / max(len(cases), 1)
        row: dict[str, Any] = {
            "hypothesis": hypothesis.name,
            "tools": tools,
            "log_path": str(log_path),
            "orchestrator": "direct",
            "orchestrator_usage": usage,
            "metrics": metrics,
            "errors": errors[:20],
            "error_count": len(errors),
        }
        if args.details:
            row["results"] = [eval_result_to_json(result) for result in eval_results]
        rows.append(row)

    if args.json:
        print(json.dumps({"run_id": run_id, "results": rows}, indent=2))
        return 0

    print(f"run_id: {run_id}")
    for row in rows:
        print()
        print(row["hypothesis"])
        print(f"  tools: {', '.join(row['tools'])}")
        print(f"  log_path: {row['log_path']}")
        usage = row["orchestrator_usage"]
        print(
            "  orchestrator_usage: "
            f"tokens={usage['total_tokens']} "
            f"input={usage['input_tokens']} output={usage['output_tokens']} "
            f"cost=${usage['total_cost']:.6f} tool_calls={usage['tool_calls']}"
        )
        if row["error_count"]:
            print(f"  error_count: {row['error_count']}")
        for name, value in row["metrics"].items():
            print(f"  {name}: {value:.4f}" if isinstance(value, float) else f"  {name}: {value}")
    return 0


def cmd_experiment(args: argparse.Namespace, config: AppConfig) -> int:
    if args.hypothesis:
        selected = set(args.hypothesis)
        config = replace(
            config,
            experiments=replace(
                config.experiments,
                hypotheses=[hypothesis for hypothesis in config.experiments.hypotheses if hypothesis.name in selected],
            ),
        )
        missing = selected - {hypothesis.name for hypothesis in config.experiments.hypotheses}
        if missing:
            raise ValueError(f"Unknown experiment hypothesis: {', '.join(sorted(missing))}")
    vector_store = None if args.reindex else make_vector_store(config)
    needs_index = args.reindex or not vector_store.exists()
    if needs_index:
        if vector_store is not None:
            close_vector_store(vector_store)
        cmd_index(args, config)
        vector_store = make_vector_store(config)

    provider = make_embedding_provider(config, vector_store.metadata())
    plugin_manager = make_plugin_manager(config)
    cases = DatasetLoader().load(config.evaluation.dataset)
    for case in cases:
        case.query = plugin_manager.prepare_query(case.query)

    run_id = uuid.uuid4().hex
    experiment_run = ExperimentRunner(
        RetrievalStrategyFactory(),
        provider,
        vector_store,
    ).run(run_id, config, cases)

    saved_rows = 0
    if config.metrics.enabled:
        repository = make_metrics_repository(config)
        repository.ensure_schema()
        metric_rows, case_rows = ExperimentMetricsMapper().to_rows(experiment_run, config, args.config)
        repository.save(metric_rows, case_rows)
        saved_rows = len(metric_rows) + len(case_rows)

    if args.json:
        print(json.dumps(experiment_run_to_json(experiment_run, saved_rows), indent=2))
        return 0

    print(f"run_id: {experiment_run.run_id}")
    print(f"suite: {experiment_run.suite}")
    for strategy_result in experiment_run.strategy_results:
        print()
        print(f"{strategy_result.strategy}:")
        for name, value in strategy_result.metrics.items():
            print(f"  {name}: {value:.4f}" if isinstance(value, float) else f"  {name}: {value}")
    if config.metrics.enabled:
        print(f"\nrecorded_rows: {saved_rows}")
    return 0


def cmd_monitor(args: argparse.Namespace, config: AppConfig) -> int:
    if args.trace is None and not config.trace.enabled:
        print("Tracing is disabled in config. Pass --trace <path> to monitor an existing trace file.")
        return 1
    trace_path = args.trace or config.trace.artifact
    TraceMonitor(
        trace_path=trace_path,
        refresh_seconds=float(args.refresh),
        max_events=int(args.max_events),
    ).run()
    return 0


def normalize_query(query: str | list[str]) -> str:
    if isinstance(query, list):
        return " ".join(query).strip()
    return query.strip()


def run_search(config: AppConfig, query: str, limit: int) -> list[SearchResult]:
    vector_store = make_vector_store(config)
    try:
        if not vector_store.exists():
            raise ValueError(f"Index not found in {store_label(config)}. Run `code-diver index` first.")
        provider = make_embedding_provider(config, vector_store.metadata())
        prepared_query = make_plugin_manager(config).prepare_query(query)
        return make_retrieval_strategy(config, provider, vector_store).search(prepared_query, limit)
    finally:
        close_vector_store(vector_store)


def make_indexing_service(config: AppConfig, progress: bool = True) -> IndexingService:
    return IndexingService(
        make_codebase_scanner(config),
        make_plugin_manager(config),
        make_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            progress=progress,
        ),
        make_trace_logger(config),
    )


def generate_local_eval_dataset(config: AppConfig, output: Path, case_count: int) -> list[dict[str, Any]]:
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        line_chunks=False,
        file_summary_chunks=True,
        file_manifest_chunks=True,
        max_symbols_per_file=config.scanner.max_symbols_per_file,
    )
    return LocalEvalDatasetGenerator(scanner).generate(config.root, output, case_count)


def make_codebase_scanner(config: AppConfig):
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        line_chunks=config.scanner.line_chunks,
        chunk_lines=config.scanner.chunk_lines,
        structural_chunks=config.scanner.structural_chunks,
        symbol_chunks=config.scanner.symbol_chunks,
        symbol_body=config.scanner.symbol_body,
        file_summary_chunks=config.scanner.file_summary_chunks,
        file_manifest_chunks=config.scanner.file_manifest_chunks,
        max_symbols_per_file=config.scanner.max_symbols_per_file,
    )
    mode = config.indexing.mode
    if mode == "scanner":
        return scanner
    if mode == "orchestrated":
        return OrchestratedCodebaseScanner(scanner, create_generation_provider(config), config, make_trace_logger(config))
    ai_scanner = AiCodebaseScanner(scanner, create_generation_provider(config), config.indexing.ai)
    if mode == "ai":
        return ai_scanner
    if mode == "hybrid":
        return HybridCodebaseScanner([scanner, ai_scanner])
    raise ValueError(f"Unknown indexing mode: {mode}")


def make_plugin_manager(config: AppConfig) -> PluginManager:
    return PluginManager([Path(path) for path in config.plugins])


def make_trace_logger(config: AppConfig) -> TraceLogger:
    return TraceLogger(config.trace)


def make_embedding_provider(config: AppConfig, payload: dict[str, Any] | None = None):
    ensure_configured_embedding_runtime(config)
    embedding = config.embedding
    if payload:
        validate_embedding_metadata(config, payload)
    provider_name = embedding.provider or str((payload or {}).get(SchemaKey.PROVIDER.value, Defaults.EMBEDDING_PROVIDER))
    model = embedding.model or (payload or {}).get(SchemaKey.MODEL.value)
    dimensions = embedding.dimensions
    if dimensions is None and provider_name != EmbeddingProviderId.OPENAI_COMPATIBLE.value:
        dimensions = (payload or {}).get(SchemaKey.DIMENSIONS.value)
    return create_embedding_provider(
        provider_name,
        model=model,
        dimensions=int(dimensions) if dimensions else None,
        api_key=embedding.api_key,
        url=embedding.url,
        project=embedding.project,
        location=embedding.location,
        batch_size=embedding.batch_size,
        retry_attempts=embedding.retry_attempts,
        retry_delay_seconds=embedding.retry_delay_seconds,
        document_prefix=embedding.document_prefix,
        query_prefix=embedding.query_prefix,
        max_input_chars=embedding.max_input_chars,
    )


def validate_embedding_metadata(config: AppConfig, payload: dict[str, Any]) -> None:
    expected_provider = config.embedding.provider
    actual_provider = str(payload.get(SchemaKey.PROVIDER.value) or "")
    if expected_provider and actual_provider and expected_provider != actual_provider:
        raise ValueError(
            "Index embedding provider mismatch: "
            f"config expects {expected_provider!r}, artifact has {actual_provider!r}. "
            "Rebuild the index with `--reindex` or select the matching config."
        )

    expected_model = config.embedding.model
    actual_model = str(payload.get(SchemaKey.MODEL.value) or "")
    if expected_model and actual_model and expected_model != actual_model:
        raise ValueError(
            "Index embedding model mismatch: "
            f"config expects {expected_model!r}, artifact has {actual_model!r}. "
            "Rebuild the index with `--reindex` or select the matching config."
        )

    expected_dimensions = config.embedding.dimensions
    actual_dimensions = payload.get(SchemaKey.DIMENSIONS.value)
    if expected_dimensions is not None and actual_dimensions is not None and int(expected_dimensions) != int(actual_dimensions):
        raise ValueError(
            "Index embedding dimensions mismatch: "
            f"config expects {expected_dimensions}, artifact has {actual_dimensions}. "
            "Rebuild the index with `--reindex` or select the matching config."
        )


def ensure_configured_embedding_runtime(config: AppConfig) -> None:
    profile_key = local_embedding_profile_key(config)
    if profile_key is None:
        return
    store = RuntimeConfigStore()
    if not store.exists():
        profile = EmbeddingProfileRegistry().get(profile_key)
        platform = next((item for item in profile.platforms if item not in {"external", "api"}), "external")
        raise RuntimeError(
            "Local embedding runtime is not configured. Run "
            f"`uv run code-diver init --platform {platform} --embedding {profile_key} --yes --start` first."
        )
    runtime = store.load()
    if runtime.embedding_profile != profile_key:
        raise RuntimeError(
            "Configured local embedding runtime does not match this embedding model. "
            f"runtime={runtime.embedding_profile}, requested={profile_key}. "
            f"Run `uv run code-diver init --embedding {profile_key}`."
        )
    EmbeddingRuntimeManager(runtime).ensure_running()


def local_embedding_profile_key(config: AppConfig) -> str | None:
    embedding = config.embedding
    if embedding.provider != EmbeddingProviderId.OPENAI_COMPATIBLE.value:
        return None
    registry = EmbeddingProfileRegistry()
    for profile in registry.profiles():
        candidate = profile.config
        if candidate.provider != EmbeddingProviderId.OPENAI_COMPATIBLE.value:
            continue
        if candidate.model == embedding.model and candidate.url == embedding.url:
            return profile.key
    return None


def make_retrieval_strategy(config: AppConfig, provider: Any, vector_store: Any):
    return RetrievalStrategyFactory().create(config.search.strategy, config, provider, vector_store)


def indexing_hypotheses(config: AppConfig, names: list[str] | None = None):
    selected_names = set(names or [])
    return [
        hypothesis
        for hypothesis in config.experiments.hypotheses
        if not selected_names or hypothesis.name in selected_names
        if "code_diver_index_selected" in resolve_hypothesis_tools(config, hypothesis.name)
    ]


def search_tool_hypotheses(config: AppConfig, names: list[str] | None = None):
    selected_names = set(names or [])
    return [
        hypothesis
        for hypothesis in config.experiments.hypotheses
        if not selected_names or hypothesis.name in selected_names
        if resolve_hypothesis_tools(config, hypothesis.name)
        if "code_diver_index_selected" not in resolve_hypothesis_tools(config, hypothesis.name)
    ]


def resolve_hypothesis_tools(config: AppConfig, hypothesis_name: str) -> list[str]:
    hypothesis = next(
        (candidate for candidate in config.experiments.hypotheses if candidate.name == hypothesis_name),
        None,
    )
    if hypothesis is None:
        return []
    if hypothesis.tools:
        return hypothesis.tools
    if hypothesis.toolset:
        return config.pi.toolsets.get(hypothesis.toolset, [])
    return config.pi.tools


def config_for_indexing_hypothesis(config: AppConfig, hypothesis_name: str, run_id: str) -> AppConfig:
    qdrant = replace(
        config.storage.qdrant,
        collection=f"{config.storage.qdrant.collection}_{hypothesis_name}_{run_id}",
    )
    return replace(
        config,
        artifact=suffixed_artifact_path(config.artifact, hypothesis_name, run_id),
        storage=replace(config.storage, qdrant=qdrant),
        graph=replace(config.graph, artifact=suffixed_artifact_path(config.graph.artifact, hypothesis_name, run_id)),
    )


def config_for_search_hypothesis(config: AppConfig, hypothesis: Any) -> AppConfig:
    search_config = config
    if getattr(hypothesis, "strategy", None):
        search_config = replace(search_config, search=replace(search_config.search, strategy=hypothesis.strategy))
    if getattr(hypothesis, "generation", None) is not None:
        search_config = replace(search_config, generation=hypothesis.generation)
    if getattr(hypothesis, "hybrid_search", None) is not None:
        search_config = replace(search_config, hybrid_search=hypothesis.hybrid_search)
    if getattr(hypothesis, "llm_rerank", None) is not None:
        search_config = replace(search_config, llm_rerank=hypothesis.llm_rerank)
    if getattr(hypothesis, "cross_encoder_rerank", None) is not None:
        search_config = replace(search_config, cross_encoder_rerank=hypothesis.cross_encoder_rerank)
    return search_config


def indexing_hypothesis_log_path(config: AppConfig, hypothesis_name: str, run_id: str) -> Path:
    base = config.trace.artifact.parent if config.trace.artifact else Path(".code-diver/traces")
    return base / "orchestrator-indexing" / run_id / f"{hypothesis_name}.jsonl"


def search_hypothesis_log_path(config: AppConfig, hypothesis_name: str, run_id: str) -> Path:
    base = config.trace.artifact.parent if config.trace.artifact else Path(".code-diver/traces")
    return base / "orchestrator-search" / run_id / f"{hypothesis_name}.jsonl"


def make_graph_indexer(config: AppConfig):
    if not config.graph.enabled:
        return None

    def build(items: list[Any]) -> None:
        GraphIndexingService(
            CodeGraphBuilder(
                ast_enabled=config.graph.ast_enabled,
                reference_edges_enabled=config.graph.reference_edges_enabled,
                call_edges_enabled=config.graph.call_edges_enabled,
            ),
            CodeGraphStore(config.graph.artifact),
        ).build(config.root, items)

    return build


def suffixed_artifact_path(path: Path, hypothesis_name: str, run_id: str) -> Path:
    return path.with_name(f"{path.stem}_{hypothesis_name}_{run_id}{path.suffix}")


def make_search_tool_handler(strategy: Any):
    kind_resolver = CodeItemIndexKindResolver()

    def handle(query: str, limit: int) -> str:
        results = strategy.search(query, limit)
        return json.dumps(
            [
                {
                    "id": result.item.id,
                    "path": result.item.path,
                    "title": result.item.title,
                    "startLine": result.item.start_line,
                    "endLine": result.item.end_line,
                    "score": result.score,
                    "indexKind": kind_resolver.resolve(result.item),
                    "preview": compact_preview(result.item.content, 360),
                }
                for result in results
            ],
            indent=2,
        )

    return handle


def format_index_composition(items: list[Any]) -> str:
    composition = IndexCompositionAnalyzer().analyze(items)
    items_by_kind = composition["items_by_kind"]
    if not items_by_kind:
        return "Index composition: empty"
    pairs = ", ".join(f"{kind}={count}" for kind, count in items_by_kind.items())
    content_mb = composition["content_bytes_total"] / 1_000_000
    return (
        f"Index composition: {pairs}; unique_paths={composition['unique_paths']}; "
        f"content_mb={content_mb:.2f}; content_bytes_mean={composition['content_bytes_mean']:.1f}"
    )


def make_rerank_tool_handler(config: AppConfig, generation_provider: Any):
    handler = RerankToolHandler(generation_provider, config.llm_rerank)

    def rerank(query: str, candidates: list[dict[str, Any]], limit: int, args: dict[str, Any]) -> dict[str, Any]:
        return handler.rerank(query, candidates, limit, args)

    return rerank


def make_ephemeral_search_tool_handler(config: AppConfig):
    scanner = CodebaseScanner(
        include=config.scanner.include,
        exclude=config.scanner.exclude,
        max_file_bytes=config.scanner.max_file_bytes,
        line_chunks=False,
        chunk_lines=config.scanner.chunk_lines,
        structural_chunks=True,
        symbol_chunks=True,
        symbol_body=True,
        file_summary_chunks=False,
        max_symbols_per_file=config.scanner.max_symbols_per_file,
    )
    service = EphemeralDeepIndexService(
        CandidateFileScanner(scanner),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            progress=False,
        ),
    )

    def search(query: str, files: list[str], limit: int, args: dict[str, Any]) -> dict[str, Any]:
        provider = make_embedding_provider(config)
        index = service.build(config.root, files[: int(args.get("fileLimit") or args.get("file_limit") or 30)], provider)
        search_result = service.search(index, provider, query, limit)
        return {
            "candidates": [
                {
                    "id": result.item.id,
                    "path": result.item.path,
                    "title": result.item.title,
                    "startLine": result.item.start_line,
                    "endLine": result.item.end_line,
                    "score": result.score,
                    "indexKind": CodeItemIndexKindResolver().resolve(result.item),
                    "breadcrumb": result.item.metadata.get("breadcrumb"),
                    "preview": compact_preview(result.item.content, 420),
                }
                for result in search_result.results
            ],
            "metrics": {
                "ephemeral_build_ms": index.build_ms,
                "ephemeral_query_ms": search_result.query_ms,
                "temporary_vectors": index.temporary_vectors,
                "cache_hits": index.cache_hits,
                "cache_misses": index.cache_misses,
                "cache_hit_rate": index.cache_hit_rate,
                "candidate_files": len(files),
            },
        }

    return search


def compact_preview(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def inspection_exclude_patterns(config: AppConfig) -> list[str]:
    return [*DEFAULT_EXCLUDES, *config.scanner.exclude]


def direct_search_eval_result(case: Any, retrieved: list[str], limit: int):
    matched_ranks = [
        rank for rank, value in enumerate(retrieved[:limit], start=1) if direct_search_matches_any(value, case.expected)
    ]
    hit = bool(matched_ranks)
    reciprocal_rank = 1.0 / matched_ranks[0] if matched_ranks else 0.0
    match_count = len(matched_ranks)
    file_metrics = direct_search_file_metrics(case.expected, retrieved[:limit], limit)
    return EvalResult(
        case_id=case.id,
        query=case.query,
        expected=case.expected,
        retrieved=retrieved[:limit],
        hit=hit,
        reciprocal_rank=reciprocal_rank,
        precision=match_count / max(len(retrieved[:limit]), 1),
        recall=min(match_count / max(len(case.expected), 1), 1.0),
        retrieved_files=file_metrics["retrieved_files"],
        bucket=EvalCaseBucketClassifier().classify(case.query),
        file_hit=file_metrics["file_hit"],
        file_reciprocal_rank=file_metrics["file_mrr"],
        file_precision_at_r=file_metrics["file_precision_at_r"],
        file_recall=file_metrics["file_recall"],
        ndcg=file_metrics["ndcg"],
        average_precision=file_metrics["average_precision"],
    )


def direct_search_matches_any(path: str, expected: list[str]) -> bool:
    return any(direct_search_matches(path, value) for value in expected)


def direct_search_matches(path: str, expected: str) -> bool:
    normalized = expected.strip()
    if normalized.startswith("glob:"):
        return fnmatch.fnmatchcase(direct_search_file_path(path), normalized.removeprefix("glob:"))
    return (
        path == normalized
        or path.startswith(normalized + "#")
        or path.startswith(normalized + "::")
        or path.startswith(normalized.rstrip("/") + "/")
    )


def direct_search_file_metrics(expected: list[str], retrieved: list[str], limit: int) -> dict[str, Any]:
    files = dedupe_preserving_order(direct_search_file_path(value) for value in retrieved[:limit])
    matched_ranks = [
        rank for rank, path in enumerate(files, start=1) if direct_search_matches_any(path, expected)
    ]
    expected_count = max(len(expected), 1)
    matched_expected_count = sum(1 for value in expected if any(direct_search_matches(path, value) for path in files))
    r = min(expected_count, limit)
    top_r = files[:r]
    return {
        "retrieved_files": files,
        "file_hit": bool(matched_ranks),
        "file_mrr": 1.0 / matched_ranks[0] if matched_ranks else 0.0,
        "file_precision_at_r": sum(1 for path in top_r if direct_search_matches_any(path, expected)) / max(r, 1),
        "file_recall": min(matched_expected_count / expected_count, 1.0),
        "ndcg": direct_search_ndcg(files, expected, limit),
        "average_precision": direct_search_average_precision(files, expected),
    }


def direct_search_file_path(value: str) -> str:
    return value.split("#", 1)[0].split("::", 1)[0]


def dedupe_preserving_order(values: Any) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def direct_search_ndcg(files: list[str], expected: list[str], limit: int) -> float:
    import math

    dcg = 0.0
    matched_expected: set[int] = set()
    for rank, path in enumerate(files[:limit], start=1):
        match_index = first_unmatched_direct_expected(path, expected, matched_expected)
        if match_index is not None:
            matched_expected.add(match_index)
            dcg += 1.0 / math.log2(rank + 1)
    ideal_relevant = min(len(expected), limit)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    return dcg / ideal if ideal else 0.0


def direct_search_average_precision(files: list[str], expected: list[str]) -> float:
    hits = 0
    total = 0.0
    matched_expected: set[int] = set()
    for rank, path in enumerate(files, start=1):
        match_index = first_unmatched_direct_expected(path, expected, matched_expected)
        if match_index is None:
            continue
        matched_expected.add(match_index)
        hits += 1
        total += hits / rank
    return total / max(len(expected), 1)


def first_unmatched_direct_expected(path: str, expected: list[str], matched: set[int]) -> int | None:
    for index, value in enumerate(expected):
        if index in matched:
            continue
        if direct_search_matches(path, value):
            return index
    return None


def direct_search_metrics(results: list[Any], durations_ms: list[float], limit: int) -> dict[str, Any]:
    metrics = {
        "cases": len(results),
        f"hit_rate@{limit}": mean(1.0 if result.hit else 0.0 for result in results),
        f"mrr@{limit}": mean(result.reciprocal_rank for result in results),
        f"precision@{limit}": mean(result.precision for result in results),
        f"recall@{limit}": mean(result.recall for result in results),
        "hit_rate@1": mean(1.0 if any(direct_search_matches_any(value, result.expected) for value in result.retrieved[:1]) else 0.0 for result in results),
        "hit_rate@3": mean(1.0 if any(direct_search_matches_any(value, result.expected) for value in result.retrieved[:3]) else 0.0 for result in results),
        "hit_rate@5": mean(1.0 if any(direct_search_matches_any(value, result.expected) for value in result.retrieved[:5]) else 0.0 for result in results),
        "file_hit_rate@1": mean(1.0 if direct_search_file_hit_at(result, 1) else 0.0 for result in results),
        "file_hit_rate@3": mean(1.0 if direct_search_file_hit_at(result, 3) else 0.0 for result in results),
        "file_hit_rate@5": mean(1.0 if direct_search_file_hit_at(result, 5) else 0.0 for result in results),
        f"file_hit_rate@{limit}": mean(1.0 if result.file_hit else 0.0 for result in results),
        f"file_mrr@{limit}": mean(result.file_reciprocal_rank for result in results),
        "file_precision@R": mean(result.file_precision_at_r for result in results),
        f"file_recall@{limit}": mean(result.file_recall for result in results),
        f"ndcg@{limit}": mean(result.ndcg for result in results),
        f"map@{limit}": mean(result.average_precision for result in results),
        "search_duration_ms_total": sum(durations_ms),
        "search_duration_ms_mean": mean(durations_ms),
        "search_duration_ms_p95": percentile(durations_ms, 0.95),
    }
    statistics = EvaluationStatistics()
    series = [
        (f"hit_rate@{limit}", (1.0 if result.hit else 0.0 for result in results), True),
        (f"mrr@{limit}", (result.reciprocal_rank for result in results), False),
        (f"precision@{limit}", (result.precision for result in results), False),
        (f"recall@{limit}", (result.recall for result in results), False),
        ("hit_rate@1", (1.0 if any(direct_search_matches_any(value, result.expected) for value in result.retrieved[:1]) else 0.0 for result in results), True),
        ("hit_rate@3", (1.0 if any(direct_search_matches_any(value, result.expected) for value in result.retrieved[:3]) else 0.0 for result in results), True),
        ("hit_rate@5", (1.0 if any(direct_search_matches_any(value, result.expected) for value in result.retrieved[:5]) else 0.0 for result in results), True),
        ("file_hit_rate@1", (1.0 if direct_search_file_hit_at(result, 1) else 0.0 for result in results), True),
        ("file_hit_rate@3", (1.0 if direct_search_file_hit_at(result, 3) else 0.0 for result in results), True),
        ("file_hit_rate@5", (1.0 if direct_search_file_hit_at(result, 5) else 0.0 for result in results), True),
        (f"file_hit_rate@{limit}", (1.0 if result.file_hit else 0.0 for result in results), True),
        (f"file_mrr@{limit}", (result.file_reciprocal_rank for result in results), False),
        ("file_precision@R", (result.file_precision_at_r for result in results), False),
        (f"file_recall@{limit}", (result.file_recall for result in results), False),
        (f"ndcg@{limit}", (result.ndcg for result in results), False),
        (f"map@{limit}", (result.average_precision for result in results), False),
        ("search_duration_ms_mean", durations_ms, False),
    ]
    for name, values, binary in series:
        metrics.update(statistics.summarize(name, values, binary=binary))
    return metrics


def direct_search_file_hit_at(result: Any, limit: int) -> bool:
    return any(direct_search_matches_any(value, result.expected) for value in result.retrieved_files[:limit])


def empty_agent_usage() -> dict[str, Any]:
    return {
        "model_calls": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "models": [],
    }


def merge_agent_usage(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in ["model_calls", "tool_calls", "input_tokens", "output_tokens", "total_tokens"]:
        target[key] += int(source.get(key) or 0)
    target["total_cost"] += float(source.get("total_cost") or 0.0)
    for model in source.get("models") or []:
        if model not in target["models"]:
            target["models"].append(model)


def mean(values: Any) -> float:
    materialized = list(values)
    if not materialized:
        return 0.0
    return sum(materialized) / len(materialized)


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round((len(ordered) - 1) * quantile)), len(ordered) - 1)
    return ordered[index]


def make_metrics_repository(config: AppConfig) -> ClickHouseMetricsRepository:
    metrics = config.metrics
    if metrics.docker_container:
        client = ClickHouseDockerClient(
            metrics.docker_container,
            metrics.username,
            metrics.password,
            metrics.timeout_seconds,
        )
    else:
        client = ClickHouseClient(metrics.url, metrics.username, metrics.password, metrics.timeout_seconds)
    return ClickHouseMetricsRepository(
        client,
        database=metrics.database,
        metrics_table=metrics.metrics_table,
        cases_table=metrics.cases_table,
        retention_days=metrics.retention_days,
    )


def store_label(config: AppConfig) -> str:
    provider = config.storage.provider
    if provider == VectorStoreProviderId.QDRANT.value:
        return f"{provider}:{config.storage.qdrant.collection}"
    return str(config.artifact)


def close_vector_store(vector_store: Any) -> None:
    close = getattr(vector_store, "close", None)
    if callable(close):
        close()


def result_to_json(result: SearchResult) -> dict[str, Any]:
    return {SchemaKey.SCORE.value: result.score, SchemaKey.ITEM.value: result.item.to_json()}


def eval_result_to_json(result: Any) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        SchemaKey.QUERY.value: result.query,
        SchemaKey.EXPECTED.value: result.expected,
        SchemaKey.RETRIEVED.value: result.retrieved,
        SchemaKey.HIT.value: result.hit,
        SchemaKey.RECIPROCAL_RANK.value: result.reciprocal_rank,
        SchemaKey.PRECISION.value: result.precision,
        SchemaKey.RECALL.value: result.recall,
        "retrieved_files": result.retrieved_files or [],
        "bucket": result.bucket,
        "top_result_kind": result.top_result_kind,
        "first_relevant_kind": result.first_relevant_kind,
        "file_hit": result.file_hit,
        "file_reciprocal_rank": result.file_reciprocal_rank,
        "file_precision_at_r": result.file_precision_at_r,
        "file_recall": result.file_recall,
        "ndcg": result.ndcg,
        "average_precision": result.average_precision,
    }


def experiment_run_to_json(run: Any, saved_rows: int) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "suite": run.suite,
        "recorded_rows": saved_rows,
        "strategies": [
            {
                "strategy": strategy_result.strategy,
                "metrics": strategy_result.metrics,
                "results": [eval_result_to_json(result) for result in strategy_result.results],
            }
            for strategy_result in run.strategy_results
        ],
    }
