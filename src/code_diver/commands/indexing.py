from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..ai_indexing import AiCodebaseScanner, HybridCodebaseScanner
from ..config import AppConfig
from ..generation import create_generation_provider
from ..graph import CodeGraphBuilder, CodeGraphStore
from ..inspection.exclude_patterns import inspection_exclude_patterns
from ..orchestration import OrchestratedCodebaseScanner
from ..pi.repository_context_resolver import build_repository_context
from ..plugins import PluginManager
from ..providers.embedding_provider_builder import make_embedding_provider
from ..runtime import QdrantRuntimeManager
from ..services import (
    CodebaseScanner,
    GraphIndexingService,
    IndexCollectionResolver,
    IndexCompositionAnalyzer,
    IndexingOptions,
    IndexingService,
    SelectedCodeItemBuilder,
    SelectedIndexingService,
    SelectedIndexPayloadParser,
)
from ..settings import Defaults, EmbeddingProviderId, VectorStoreProviderId
from ..store import create_vector_store
from ..tracing import TraceLogger

INDEX_MAINTENANCE_COMMANDS = {"clear", "prune", "reset"}


def status_console() -> Console:
    """Return a rich Console configured for status output on stderr."""
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
    """Render a one-line status message with code-diver badge to stderr."""
    status_console().print(f"[{style}]\\[code-diver][/{style}] {message}")


@contextlib.contextmanager
def render_activity(message: str, enabled: bool = True, style: str = "cyan"):
    """Show a transient spinner with a message while a block executes."""
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
    """Ensure backing storage services (e.g. Qdrant) are running if managed."""
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
    """Instantiate a vector store for config, ensuring runtime if needed."""
    ensure_storage_runtime(config, progress=progress)
    return create_vector_store(config)


def close_vector_store(vector_store: Any) -> None:
    """Safely close vector store if close method exists."""
    close = getattr(vector_store, "close", None)
    if callable(close):
        close()


def store_label(config: AppConfig) -> str:
    """Return a descriptive label for the active index store."""
    provider = config.storage.provider
    if provider == VectorStoreProviderId.QDRANT.value:
        return f"{provider}:{config.storage.qdrant.collection}"
    return str(config.artifact)


def current_repo_collection_prefix(config: AppConfig) -> str:
    """Extract repository prefix from Qdrant collection name."""
    collection = config.storage.qdrant.collection
    marker = "__emb_"
    if marker in collection:
        return collection.split(marker, 1)[0]
    return collection


def resolve_index_collection(config: AppConfig) -> AppConfig:
    """Resolve and update index collection name in config."""
    return IndexCollectionResolver().resolve(config)


def is_index_maintenance_command(value: object) -> bool:
    """Check if value is an index maintenance subcommand."""
    return value is not None and str(value) in INDEX_MAINTENANCE_COMMANDS


def index_write_mode_label(args: argparse.Namespace) -> str:
    """Return descriptive write mode label for indexing."""
    if bool(getattr(args, "override_repo", False)):
        return "override repo collections"
    if bool(getattr(args, "update_index", False) or getattr(args, "reindex", False)):
        return "update current collection"
    return "create new collection"


def embedding_activity_message(config: AppConfig) -> str:
    """Generate display message for embedding initialization activity."""
    model = config.embedding.model or "provider default"
    provider = config.embedding.provider or Defaults.EMBEDDING_PROVIDER
    if config.embedding.provider == EmbeddingProviderId.OPENAI_COMPATIBLE.value:
        return (
            "checking embedding runtime from init config and preparing local client: "
            f"model={model} endpoint={config.embedding.url}"
        )
    if config.embedding.provider in {"gemini", "vertex"}:
        location = (
            f" location={config.embedding.location}"
            if config.embedding.location
            else ""
        )
        return f"creating API embedding client: provider={provider} model={model}{location}"
    return f"creating embedding client: provider={provider} model={model}"


def index_profile_label(config: AppConfig) -> str:
    """Return a human-readable label for the active indexing profile."""
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and config.scanner.documentation_summary_chunks
        and config.scanner.documentation_manifest_chunks
        and config.scanner.documentation_chunk_chunks
        and not config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H14 text-graph code/docs locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and config.scanner.documentation_summary_chunks
        and config.scanner.documentation_manifest_chunks
        and not config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H12 dual-lane code/docs locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H7.1 API manifest file locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and not config.scanner.file_api_manifest_chunks
        and config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H9 body-evidence file locator"
    if (
        config.scanner.file_summary_chunks
        and config.scanner.file_manifest_chunks
        and not config.scanner.file_api_manifest_chunks
        and not config.scanner.file_body_evidence_chunks
        and not config.scanner.line_chunks
        and not config.scanner.structural_chunks
        and not config.scanner.symbol_chunks
    ):
        return "H6.1 file locator"
    return "custom"


def index_content_label(config: AppConfig) -> str:
    """Return comma-separated string describing enabled index content types."""
    enabled: list[str] = []
    if config.scanner.file_summary_chunks:
        enabled.append("file summaries")
    if config.scanner.file_manifest_chunks:
        enabled.append("file manifests")
    if config.scanner.file_api_manifest_chunks:
        enabled.append("API manifests")
    if config.scanner.file_body_evidence_chunks:
        enabled.append("body evidence")
    if config.scanner.file_purpose_chunks:
        enabled.append("file purpose")
    if config.scanner.symbol_chunk_chunks:
        enabled.append("symbol chunks")
    if config.scanner.documentation_summary_chunks:
        enabled.append("doc summaries")
    if config.scanner.documentation_manifest_chunks:
        enabled.append("doc manifests")
    if config.scanner.documentation_chunk_chunks:
        enabled.append("doc chunks")
    if config.scanner.line_chunks:
        enabled.append("line chunks")
    if config.scanner.structural_chunks:
        enabled.append("AST chunks")
    if config.scanner.symbol_chunks:
        enabled.append("symbols")
    return ", ".join(enabled) if enabled else "scanner output"


def graph_label(config: AppConfig) -> str:
    """Return descriptive status of graph indexing configuration."""
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
    """Generate display message for graph construction activity."""
    return (
        "building graph artifact from indexed items: "
        f"items={item_count} artifact={config.graph.artifact} {graph_label(config)}"
    )


def format_index_composition(items: list[Any]) -> str:
    """Summarize index composition by kind, paths, and total bytes."""
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


def make_codebase_scanner(config: AppConfig):
    """Instantiate the configured scanner or AI/orchestrated scanner."""
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
        file_summary_head_line_max_chars=config.scanner.file_summary_head_line_max_chars,
        file_summary_head_block_max_chars=config.scanner.file_summary_head_block_max_chars,
        file_summary_compact_budget=config.scanner.file_summary_compact_budget,
        file_summary_compact_path=config.scanner.file_summary_compact_path,
        file_summary_term_stopwords=config.scanner.file_summary_term_stopwords,
        file_manifest_chunks=config.scanner.file_manifest_chunks,
        file_manifest_symbol_surface=config.scanner.file_manifest_symbol_surface,
        file_api_manifest_chunks=config.scanner.file_api_manifest_chunks,
        file_body_evidence_chunks=config.scanner.file_body_evidence_chunks,
        file_purpose_chunks=config.scanner.file_purpose_chunks,
        symbol_chunk_chunks=config.scanner.symbol_chunk_chunks,
        documentation_summary_chunks=config.scanner.documentation_summary_chunks,
        documentation_manifest_chunks=config.scanner.documentation_manifest_chunks,
        documentation_chunk_chunks=config.scanner.documentation_chunk_chunks,
        max_symbols_per_file=config.scanner.max_symbols_per_file,
    )
    mode = config.indexing.mode
    if mode == "scanner":
        return scanner
    if mode == "orchestrated":
        return OrchestratedCodebaseScanner(
            scanner,
            create_generation_provider(config),
            config,
            make_trace_logger(config),
        )
    ai_scanner = AiCodebaseScanner(
        scanner, create_generation_provider(config), config.indexing.ai
    )
    if mode == "ai":
        return ai_scanner
    if mode == "hybrid":
        return HybridCodebaseScanner([scanner, ai_scanner])
    raise ValueError(f"Unknown indexing mode: {mode}")


def make_plugin_manager(config: AppConfig) -> PluginManager:
    """Instantiate plugin manager with configured plugins."""
    return PluginManager([Path(path) for path in config.plugins])


def make_trace_logger(config: AppConfig) -> TraceLogger:
    """Instantiate trace logger from config."""
    return TraceLogger(config.trace)


def make_indexing_service(config: AppConfig, progress: bool = True) -> IndexingService:
    """Build full IndexingService with scanner, plugins, store, and options."""
    return IndexingService(
        make_codebase_scanner(config),
        make_plugin_manager(config),
        make_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            embedding_max_input_tokens=config.embedding.max_input_tokens,
            embedding_token_safety_margin=config.embedding.token_safety_margin,
            progress=progress,
        ),
        make_trace_logger(config),
    )


def suffixed_artifact_path(
    path: Path, hypothesis_name: str, run_id: str = ""
) -> Path:
    """Return artifact path suffixed with hypothesis name and optional run ID."""
    suffix = f"{hypothesis_name}_{run_id}" if run_id else hypothesis_name
    return path.with_name(f"{path.stem}_{suffix}{path.suffix}")


def config_for_indexing_hypothesis(
    config: AppConfig,
    hypothesis: Any,
    run_id: str = "",
) -> AppConfig:
    """Isolate storage and graph artifacts for an indexing hypothesis run."""
    hypothesis_name = getattr(hypothesis, "name", None) or str(hypothesis)
    suffix = f"{hypothesis_name}_{run_id}" if run_id else hypothesis_name
    qdrant = replace(
        config.storage.qdrant,
        collection=f"{config.storage.qdrant.collection}_{suffix}",
    )
    return replace(
        config,
        artifact=suffixed_artifact_path(config.artifact, hypothesis_name, run_id),
        storage=replace(config.storage, qdrant=qdrant),
        graph=replace(
            config.graph,
            artifact=suffixed_artifact_path(
                config.graph.artifact, hypothesis_name, run_id
            ),
        ),
    )


def prepare_index_collection(
    first: AppConfig | argparse.Namespace | None = None,
    second: AppConfig | argparse.Namespace | None = None,
    *,
    config: AppConfig | None = None,
    args: argparse.Namespace | None = None,
    progress: bool = True,
) -> None:
    """Prepare Qdrant collection before indexing, checking overrides and existing entries."""
    resolved_config = config
    resolved_args = args
    if first is not None:
        if isinstance(first, AppConfig):
            resolved_config = first
        else:
            resolved_args = first
    if second is not None:
        if isinstance(second, AppConfig):
            resolved_config = second
        else:
            resolved_args = second

    if resolved_config is None or resolved_args is None:
        raise ValueError(
            "Both config and args must be provided to prepare_index_collection."
        )

    if resolved_config.storage.provider != VectorStoreProviderId.QDRANT.value:
        return
    vector_store = make_vector_store(resolved_config)
    try:
        if bool(getattr(resolved_args, "override_repo", False)):
            prefix = current_repo_collection_prefix(resolved_config)
            with render_activity(
                f"removing existing Qdrant collections for repo prefix: {prefix}",
                enabled=progress,
            ):
                deleted = vector_store.delete_collections_with_prefix(prefix)
            if progress:
                render_status_line(
                    f"removed {len(deleted)} repo collection entries", "yellow"
                )
            return
        if bool(
            getattr(resolved_args, "update_index", False)
            or getattr(resolved_args, "reindex", False)
        ):
            return
        if vector_store.exists():
            raise RuntimeError(
                f"Index collection already exists: {resolved_config.storage.qdrant.collection}. "
                "Use `--update-index` to replace only this collection, or `--override-repo` "
                "to delete all collections for this repository before indexing."
            )
    finally:
        close_vector_store(vector_store)


def cmd_index(args: argparse.Namespace, config: AppConfig) -> int:
    """Build or update code and document index."""
    if is_index_maintenance_command(getattr(args, "index_root", None)):
        return cmd_index_clear(args, config)
    if bool(getattr(args, "all", False)):
        raise ValueError("`--all` is only supported with `code-diver index clear`.")
    progress = not bool(
        getattr(args, "no_progress", False) or getattr(args, "quiet", False)
    )
    ensure_storage_runtime(config, progress=progress)
    prepare_index_collection(config=config, args=args, progress=progress)
    with render_activity("building repository context artifact", enabled=progress):
        repository_context_result = build_repository_context(config)
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
                (
                    "repo ctx",
                    (
                        f"{repository_context_result.mode} ({repository_context_result.chars} chars)"
                        if repository_context_result is not None
                        else "disabled"
                    ),
                ),
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
                (
                    "endpoint",
                    config.embedding.url
                    or config.embedding.location
                    or "provider default",
                ),
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
            with render_activity(
                graph_activity_message(config, len(items)), enabled=progress
            ):
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
                render_status_line(
                    f"saved graph artifact: {config.graph.artifact}", "green"
                )
        print(
            f"Indexed {len(items)} items -> {store_label(config)} "
            f"({provider.name}, model={provider.model}, dimensions={provider.dimensions})"
        )
        print(format_index_composition(items))
    except KeyboardInterrupt:
        render_status_line(
            "indexing interrupted; staged index writes were discarded", "yellow"
        )
        raise
    finally:
        close_vector_store(indexing_service.vector_store)
    return 0


def cmd_index_clear(args: argparse.Namespace, config: AppConfig) -> int:
    """Delete Qdrant index collections for current repo or all collections."""
    if bool(
        getattr(args, "update_index", False) or getattr(args, "override_repo", False)
    ):
        raise ValueError(
            "`index clear` cannot be combined with `--update-index` or `--override-repo`."
        )
    if config.storage.provider != VectorStoreProviderId.QDRANT.value:
        raise ValueError("`index clear` is only supported for Qdrant storage.")
    progress = not bool(
        getattr(args, "no_progress", False) or getattr(args, "quiet", False)
    )
    ensure_storage_runtime(config, progress=progress)
    prefix = (
        Defaults.QDRANT_COLLECTION
        if bool(getattr(args, "all", False))
        else current_repo_collection_prefix(config)
    )
    scope = (
        "all Code Diver index collections"
        if bool(getattr(args, "all", False))
        else "current repository collections"
    )
    if progress:
        render_status_panel(
            "Index Clear",
            [
                ("scope", scope),
                ("prefix", prefix),
                (
                    "store",
                    config.storage.qdrant.url
                    if config.storage.qdrant.location is None
                    else config.storage.qdrant.location,
                ),
            ],
            border_style="yellow",
        )
    vector_store = make_vector_store(config)
    try:
        with render_activity(
            f"deleting Qdrant index collections: {prefix}",
            enabled=progress,
            style="yellow",
        ):
            deleted = vector_store.delete_collections_with_prefix(prefix)
    finally:
        close_vector_store(vector_store)
    print(f"Deleted {len(deleted)} Qdrant collection entries for prefix `{prefix}`.")
    if deleted and not bool(getattr(args, "quiet", False)):
        for name in deleted:
            print(f"  {name}")
    return 0


def cmd_index_selected(args: argparse.Namespace, config: AppConfig) -> int:
    """Index selective code items provided via stdin JSON."""
    selections = SelectedIndexPayloadParser().parse(sys.stdin.read())
    built = SelectedCodeItemBuilder(
        config.root,
        config.scanner.chunk_lines,
        inspection_exclude_patterns(config),
    ).build(selections)
    if not built.items:
        payload = {
            "indexed": 0,
            "skipped": built.skipped,
            "store": store_label(config),
            "items": [],
        }
        print(
            json.dumps(payload, indent=2)
            if getattr(args, "json", False)
            else "Indexed 0 selected items."
        )
        return 0
    provider = make_embedding_provider(config)
    service = SelectedIndexingService(
        make_vector_store(config),
        IndexingOptions(
            embedding_batch_size=config.embedding.batch_size,
            embedding_workers=config.embedding.workers,
            embedding_max_input_chars=config.embedding.max_input_chars,
            embedding_max_input_tokens=config.embedding.max_input_tokens,
            embedding_token_safety_margin=config.embedding.token_safety_margin,
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
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        print(f"Indexed {len(items)} selected items -> {store_label(config)}")
        for skipped in built.skipped:
            print(f"skipped: {skipped}", file=sys.stderr)
    return 0


__all__ = [
    "INDEX_MAINTENANCE_COMMANDS",
    "close_vector_store",
    "cmd_index",
    "cmd_index_clear",
    "cmd_index_selected",
    "config_for_indexing_hypothesis",
    "current_repo_collection_prefix",
    "embedding_activity_message",
    "ensure_storage_runtime",
    "format_index_composition",
    "graph_activity_message",
    "graph_label",
    "index_content_label",
    "index_profile_label",
    "index_write_mode_label",
    "is_index_maintenance_command",
    "make_codebase_scanner",
    "make_indexing_service",
    "make_plugin_manager",
    "make_trace_logger",
    "make_vector_store",
    "prepare_index_collection",
    "render_activity",
    "render_status_line",
    "render_status_panel",
    "resolve_index_collection",
    "status_console",
    "store_label",
    "suffixed_artifact_path",
]
